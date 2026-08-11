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

# Frontier continuity test -- see _merge_continuous_contexts.
#
# The reach has to clear the widest thing that can be drawn *inside* a
# context without ending it -- a selection bar. At WORK_WIDTH such a bar
# is a handful of pixels across, so a reach of a few more than that
# samples real background on both sides of one instead of landing inside
# it. Reaching much further would start comparing genuinely distant
# areas, which is what the adjacency requirement below is for.
FRONTIER_REACH = 8              # work-scale px to look across a seam
MIN_FRONTIER_PIXELS = 20        # below this the two barely face each other
CONTINUITY_TOLERANCE = 3.0      # in units of the sampled strips' own dispersion
CONTINUITY_FLOOR = 1.5          # colour units; below this a difference is sensor noise


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
    kept = [
        label for label in range(1, count)
        if stats[label, cv2.CC_STAT_AREA] / small_area >= MIN_REGION_AREA_RATIO
    ]

    boxes: list[Geometry] = []
    for group in _merge_continuous_contexts(lab, labels, kept):
        x0 = min(stats[label, cv2.CC_STAT_LEFT] for label in group)
        y0 = min(stats[label, cv2.CC_STAT_TOP] for label in group)
        x1 = max(stats[label, cv2.CC_STAT_LEFT] + stats[label, cv2.CC_STAT_WIDTH]
                 for label in group)
        y1 = max(stats[label, cv2.CC_STAT_TOP] + stats[label, cv2.CC_STAT_HEIGHT]
                 for label in group)
        boxes.append(Geometry(int(x0 / scale), int(y0 / scale),
                              int((x1 - x0) / scale), int((y1 - y0) / scale)))

    return boxes if len(boxes) > 1 else []


def _merge_continuous_contexts(
    lab: Any, labels: Any, kept: list[int]
) -> list[list[int]]:
    """Rejoin what a marker split, as opposed to what a context change did.

    A selection bar is a strong gradient discontinuity running the full
    width of the column it sits in, so the edge test above cuts there:
    the menu above the bar and the menu below it become two regions, and
    the highlighted entry -- sitting inside the bar, straddling the seam
    -- lands in neither. It is then compared against no peers at all,
    which is exactly the comparison that would have identified it. The
    highlight defeats its own detection, and the sharper the photo, the
    more reliably it does so.

    A marker and a boundary are told apart by looking at the surface, not
    at the primitives -- deriving regions from primitive layout is the
    circularity §E4 rules out. The question asked here is whether the
    background *continues* across the frontier: two areas that differ in
    context differ in appearance right where they meet, while a stripe
    drawn inside one context has the same background on either side of
    it. Sampling only next to the frontier is what keeps this compatible
    with a region that varies smoothly across its extent -- a gradient
    barely moves over the few pixels being compared, so the vertical
    blue-to-white sidebar that motivated gradient-based segmentation in
    the first place still reads as one context rather than two.

    The tolerance is expressed in units of the sampled strips' own
    dispersion, so nothing here is calibrated to a particular interface
    (P1/P6).
    """
    parent = {label: label for label in kept}

    def find(label: int) -> int:
        while parent[label] != label:
            parent[label] = parent[parent[label]]
            label = parent[label]
        return label

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (2 * FRONTIER_REACH + 1, 2 * FRONTIER_REACH + 1)
    )
    masks = {label: (labels == label).astype(np.uint8) for label in kept}
    grown = {label: cv2.dilate(mask, kernel) for label, mask in masks.items()}

    for i, a in enumerate(kept):
        for b in kept[i + 1:]:
            # The strip of each region that faces the other. Taking each
            # side from its own region, rather than from the thin seam
            # between them, is what survives a marker several pixels wide
            # -- sampling the seam itself lands inside the marker and
            # measures the marker's own colour twice.
            side_a = lab[(masks[a] & grown[b]).astype(bool)]
            side_b = lab[(masks[b] & grown[a]).astype(bool)]
            # Doubles as the adjacency test: regions that do not face each
            # other contribute no pixels here, however alike they look.
            if len(side_a) < MIN_FRONTIER_PIXELS or len(side_b) < MIN_FRONTIER_PIXELS:
                continue
            if _same_background(side_a, side_b):
                union(a, b)

    groups: dict[int, list[int]] = {}
    for label in kept:
        groups.setdefault(find(label), []).append(label)
    return list(groups.values())


def _same_background(side_a: Any, side_b: Any) -> bool:
    """Do these two samples describe one background or two?

    Judged against the samples' own spread rather than a fixed colour
    distance: a noisy photograph and a clean screenshot disagree about
    what counts as "the same colour", and only the sample can say.
    """
    median_a = np.median(side_a, axis=0)
    median_b = np.median(side_b, axis=0)
    difference = float(np.linalg.norm(median_a - median_b))
    spread = max(
        float(np.median(np.abs(side_a - median_a), axis=0).mean()),
        float(np.median(np.abs(side_b - median_b), axis=0).mean()),
        CONTINUITY_FLOOR,
    )
    return difference <= CONTINUITY_TOLERANCE * spread


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
