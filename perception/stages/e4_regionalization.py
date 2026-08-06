"""E4 -- Regionalisation. Delimit where comparing is legitimate.

This is where the engine's known failure gets fixed at the root. The
prototype compared a menu item against the *whole screen's* colour, so on
a layout with a light menu column beside a dark settings panel the
reference was a blend of two unrelated contexts and no threshold could
rescue it. The fix is not a better threshold, it is establishing the
right context first.

Two requirements from §E4 shape the whole approach:

* **Regions come from the surface's visual context, not from where the
  primitives happen to sit.** Deriving regions from primitive layout is
  circular -- primitives cluster according to the region, so defining the
  region by how they cluster assumes the answer. It is also what locked
  the prototype into a horizontal reading of layout.

* **A context may vary smoothly across its extent and still be one
  context.** Treating constancy as the test breaks immediately on real
  interfaces: the menu column that motivated this work is a vertical
  gradient from blue to near-white, and any "uniform colour region"
  detector splits it into slices.

Hence boundaries are found by *gradient discontinuity* rather than colour
constancy. A smooth ramp produces a low per-pixel gradient however far it
travels overall; a real boundary between two contexts produces a high one.
The threshold is taken from the surface's own gradient distribution, so
nothing here is calibrated to a particular interface (P1/P6).
"""
from typing import Any

import cv2
import numpy as np

from ..model import (
    Abstention,
    Geometry,
    Perception,
    Region,
    make_ids,
)
from ..pipeline import StageOutput

WORK_WIDTH = 320                # segmentation runs coarse: structure, not texture
SMOOTHING = 9
EDGE_PERCENTILE = 88.0          # relative to this surface's own gradients
MIN_REGION_AREA_RATIO = 0.02
MIN_PRIMITIVE_OVERLAP = 0.5     # of the primitive's own area


class Regionalisation:
    name = "E4.regionalisation"
    produces = "region"
    consumes = ("surface", "primitive")

    def __init__(self, edge_percentile: float = EDGE_PERCENTILE):
        self.edge_percentile = edge_percentile

    def run(self, perception: Perception) -> StageOutput:
        surface = perception.surface
        if surface is None:
            return StageOutput(
                abstentions=(
                    Abstention(stage=self.name, level="region", scope_id=None,
                               reason="no_surface"),
                )
            )

        boxes = _segment_contexts(surface.image, self.edge_percentile)
        abstentions: list[Abstention] = []
        notes: list[str] = []

        if not boxes:
            # Degrade openly: one region covering everything. This is the
            # prototype's old behaviour, and recording it as an abstention
            # is the difference between a known limitation and a silent one.
            boxes = [Geometry(0, 0, surface.width, surface.height)]
            abstentions.append(
                Abstention(
                    stage=self.name, level="region", scope_id=None,
                    reason="no_visual_context_boundary_found",
                    detail={"effect": "whole surface treated as one context"},
                )
            )
            notes.append("fallback: single region")

        boxes = sorted(boxes, key=lambda g: (g.y, g.x, g.w, g.h))
        ids = make_ids("r", len(boxes))

        assigned: dict[str, list[str]] = {rid: [] for rid in ids}
        unassigned: list[str] = []
        for primitive in perception.primitives:
            rid = _best_region(primitive.geometry, boxes, ids)
            if rid is None:
                unassigned.append(primitive.id)
            else:
                assigned[rid].append(primitive.id)

        if unassigned:
            abstentions.append(
                Abstention(
                    stage=self.name, level="region", scope_id=None,
                    reason="primitives_outside_any_region",
                    detail={"count": len(unassigned), "ids": unassigned[:20]},
                )
            )

        regions = tuple(
            Region(
                id=rid,
                geometry=box,
                primitive_ids=tuple(assigned[rid]),
                confidence=1.0 if len(boxes) > 1 else 0.4,
                context={"area_ratio": round(box.area / float(surface.width * surface.height), 4)},
            )
            for rid, box in zip(ids, boxes)
        )
        notes.append(f"{len(regions)} region(s)")

        return StageOutput(
            products=regions,
            abstentions=tuple(abstentions),
            notes=tuple(notes),
            parameters={
                "edge_percentile": self.edge_percentile,
                "work_width": WORK_WIDTH,
            },
        )


def _segment_contexts(image: Any, edge_percentile: float) -> list[Geometry]:
    """Find areas separated by gradient discontinuities.

    Working small and heavily smoothed is deliberate: at this scale text
    and icons disappear into their background, which is exactly what we
    want -- a region is a backdrop, and the things sitting on it must not
    carve it up.
    """
    h, w = image.shape[:2]
    scale = WORK_WIDTH / float(w)
    small = cv2.resize(image, (WORK_WIDTH, max(1, int(round(h * scale)))),
                       interpolation=cv2.INTER_AREA)

    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)
    lab = cv2.GaussianBlur(lab, (SMOOTHING, SMOOTHING), 0)

    # Gradient magnitude summed over the colour channels. A slow ramp
    # contributes almost nothing here no matter how far it travels; a
    # context boundary contributes a lot.
    magnitude = np.zeros(lab.shape[:2], dtype=np.float32)
    for channel in range(3):
        gx = cv2.Sobel(lab[:, :, channel], cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(lab[:, :, channel], cv2.CV_32F, 0, 1, ksize=3)
        magnitude += cv2.magnitude(gx, gy)

    threshold = float(np.percentile(magnitude, edge_percentile))
    if threshold <= 1e-6:
        return []
    boundary = (magnitude >= threshold).astype(np.uint8)
    boundary = cv2.morphologyEx(
        boundary, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    )

    interior = (1 - boundary).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(interior, connectivity=4)

    small_area = float(interior.shape[0] * interior.shape[1])
    boxes: list[Geometry] = []
    for label in range(1, count):
        area = stats[label, cv2.CC_STAT_AREA]
        if area / small_area < MIN_REGION_AREA_RATIO:
            continue
        x = stats[label, cv2.CC_STAT_LEFT] / scale
        y = stats[label, cv2.CC_STAT_TOP] / scale
        bw = stats[label, cv2.CC_STAT_WIDTH] / scale
        bh = stats[label, cv2.CC_STAT_HEIGHT] / scale
        boxes.append(Geometry(int(x), int(y), int(bw), int(bh)))

    return boxes if len(boxes) > 1 else []


def _best_region(g: Geometry, boxes: list[Geometry], ids: list[str]) -> str | None:
    """Smallest region containing most of the primitive.

    Smallest, not first: regions may nest, and the tightest enclosing
    context is the one a comparison should happen in.
    """
    best_id, best_area = None, None
    for rid, box in zip(ids, boxes):
        overlap = g.intersection_area(box)
        if overlap < MIN_PRIMITIVE_OVERLAP * max(1, g.area):
            continue
        if best_area is None or box.area < best_area:
            best_id, best_area = rid, box.area
    return best_id
