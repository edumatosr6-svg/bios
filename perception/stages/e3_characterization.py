"""E3 -- Characterisation. Measure. Only that.

No comparison happens here. A descriptor is a property of one primitive
measured on its own; whether that value is unusual is a question about a
population, which does not exist until E6. Keeping the two apart is what
stops absolute thresholds creeping into the engine.

Two measurement decisions are promoted from the prototype's
`selection.py`, because they were right and were the expensive part to
learn:

* **Background is sampled from the bbox perimeter, not the whole crop.**
  Text boxes hug their glyphs -- measured ink coverage of 51-73% on real
  captures -- so "most common colour in the crop" is frequently the glyph
  colour. An early version made exactly that mistake and flagged 39.5% of
  all lines as highlighted. A median over a border ring is
  background-dominated because glyphs concentrate in the interior.

* **Ink is the pixels furthest from that background**, not the crop mean.

Colour is measured in a perceptually uniform space with lightness kept
separate from chromaticity, because they are different signal channels:
an item dimmed to show it is unavailable moves in lightness, an item
recoloured to show it is selected moves in chromaticity. A single
distance would blur two states into one number. (The space is an
implementation choice; the separation is the requirement.)
"""
from typing import Any

import cv2
import numpy as np

from ..model import Abstention, Descriptors, Geometry, Perception
from ..pipeline import StageOutput

MIN_INK_FRACTION = 0.02         # below this the "ink" is noise, not glyphs
INK_PERCENTILE = 90

# A focus ring is drawn *around* a control, not inside the OCR box that
# hugs its glyphs -- everything else this stage measures samples inside
# g, this alone has to sample outside it. Fixed surface-pixel padding,
# same style of constant as E4's FRONTIER_REACH: tuned on this camera's
# dropdown text height (~17-20px canonical), not scale-free across
# capture resolutions -- revisit if that changes materially.
BORDER_RING_PAD = 3
MIN_BORDER_RING_PIXELS = 20


class Characterisation:
    name = "E3.characterisation"
    produces = "descriptors"
    consumes = ("surface", "primitive")

    def run(self, perception: Perception) -> StageOutput:
        surface = perception.surface
        if surface is None or not perception.primitives:
            return StageOutput(
                products={},
                abstentions=(
                    Abstention(
                        stage=self.name, level="descriptors", scope_id=None,
                        reason="nothing_to_characterise",
                    ),
                ),
            )

        lab = cv2.cvtColor(surface.image, cv2.COLOR_BGR2LAB).astype(np.float32)
        occupied = _occupancy_mask(lab.shape[:2], perception.primitives)
        out: dict[str, Descriptors] = {}
        abstentions: list[Abstention] = []

        for primitive in perception.primitives:
            values, invalid, problem = _measure(
                lab, primitive.geometry, primitive.kind, occupied
            )
            out[primitive.id] = Descriptors(
                primitive_id=primitive.id,
                values=values,
                invalid=frozenset(invalid),
            )
            if problem:
                abstentions.append(
                    Abstention(
                        stage=self.name, level="descriptors",
                        scope_id=primitive.id, reason=problem,
                    )
                )

        return StageOutput(
            products=out,
            abstentions=tuple(abstentions),
            notes=(f"{len(out)} primitives characterised",),
            parameters={"ink_percentile": INK_PERCENTILE, "space": "perceptual_lab"},
        )


def _occupancy_mask(shape: tuple[int, int], primitives: Any) -> Any:
    """Where every *symbolic* primitive already is, on the surface.

    What `border_strength` (below) needs to tell apart is "free field
    around this control" from "the next line of body text starts right
    here" -- and only the primitive list can say which pixels are
    already claimed by *readable text*. Built once per surface, not per
    primitive: it is the same mask for everyone being measured.

    Structural primitives (rules, filled rects) are deliberately left
    out of this mask, unlike every other detected thing. A strong focus
    ring is exactly the kind of shape `structural:filled_rects` and
    `structural:rules` already catch on their own -- excluding them here
    would black out the one place a real border shows up, mistaking the
    signal for the noise it exists to filter out.
    """
    mask = np.zeros(shape, dtype=bool)
    h, w = shape
    for primitive in primitives:
        if primitive.kind != "symbolic":
            continue
        g = primitive.geometry
        x0, y0 = max(0, g.x), max(0, g.y)
        x1, y1 = min(w, g.right), min(h, g.bottom)
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = True
    return mask


def _measure(
    lab: Any, g: Geometry, kind: str, occupied: Any
) -> tuple[dict[str, Any], set[str], str | None]:
    h, w = lab.shape[:2]
    x0, y0 = max(0, g.x), max(0, g.y)
    x1, y1 = min(w, g.right), min(h, g.bottom)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return {}, {"bg_local", "ink_color", "contrast_polarity"}, "degenerate_crop"

    crop = lab[y0:y1, x0:x1]
    ring = _perimeter(crop)
    bg = np.median(ring, axis=0)
    bg_uniformity = float(ring.std(axis=0).mean())

    values: dict[str, Any] = {
        "bg_local": [float(c) for c in bg],
        "bg_uniformity": bg_uniformity,
        "area": g.area,
        "aspect": g.w / max(1.0, float(g.h)),
    }
    invalid: set[str] = set()

    flat = crop.reshape(-1, 3)
    distances = np.linalg.norm(flat - bg, axis=1)
    cutoff = float(np.percentile(distances, INK_PERCENTILE))
    ink_pixels = flat[distances >= max(cutoff, 1e-6)]
    ink_fraction = float(len(ink_pixels)) / float(len(flat))

    if kind == "structural":
        # A rule or a fill has no ink; its interior colour is the signal.
        interior = crop[crop.shape[0] // 4: 3 * crop.shape[0] // 4,
                        crop.shape[1] // 4: 3 * crop.shape[1] // 4]
        if interior.size:
            fill = np.median(interior.reshape(-1, 3), axis=0)
            values["fill_color"] = [float(c) for c in fill]
            values["fill_uniformity"] = float(interior.reshape(-1, 3).std(axis=0).mean())
        return values, invalid, None

    # Independent of whether ink was found below -- a focus ring exists
    # or not regardless of glyph legibility, so this is not gated by the
    # ink-fraction bailout the way ink_color etc. are.
    ring = _border_ring(lab, g, occupied)
    if ring is not None and len(ring) >= MIN_BORDER_RING_PIXELS:
        values["border_strength"] = float(ring[:, 0].std())
    else:
        invalid.add("border_strength")

    if ink_fraction < MIN_INK_FRACTION or not len(ink_pixels):
        invalid.update({"ink_color", "contrast_polarity", "contrast_magnitude",
                        "visual_weight"})
        return values, invalid, "no_ink_found"

    ink = ink_pixels.mean(axis=0)
    values["ink_color"] = [float(c) for c in ink]

    # Lightness kept apart from chromaticity: separate channels, not one
    # distance. Index 0 is lightness in this space; 1 and 2 are chroma.
    values["ink_lightness"] = float(ink[0])
    values["ink_chroma"] = [float(ink[1]), float(ink[2])]
    values["bg_lightness"] = float(bg[0])

    delta_l = float(ink[0] - bg[0])
    values["contrast_polarity"] = 1.0 if delta_l >= 0 else -1.0
    values["contrast_magnitude"] = abs(delta_l)

    # Ink coverage as the v1 proxy for visual weight. The requirement is
    # weight comparable within a class; the technique is free to change.
    strong = float((distances >= cutoff).sum())
    values["visual_weight"] = strong / float(len(flat))

    return values, invalid, None


def _border_ring(lab: Any, g: Geometry, occupied: Any) -> Any | None:
    """Pixels in a thin band just outside the primitive's own bbox --
    and outside every *other* primitive's bbox too.

    A real focus ring shows up here as high dispersion -- part of the
    band sits on the bright/dark ring itself, part on the plain field
    beside it. An unfocused control has one flat colour on both sides,
    so the same band reads as low dispersion. `border_strength` (the
    caller) is deliberately the ring's own std, not a distance to
    anything, so an unusually flat surrounding is not mistaken for a
    border by whatever compares it later -- see S6_border in
    perception/stages/e7_state.py, which only counts an *increase*.

    The `occupied` exclusion is what keeps that reasoning honest on body
    text: a paragraph's first line sits a few px above its own wrapped
    continuation, with near-zero gap. Without excluding neighbouring
    primitives, the ring samples *their* glyphs, not free field, and
    "densely packed text" reads as a dispersion spike indistinguishable
    from a real border -- measured on a live capture, that false ring
    beat its class by 3.5x. Free field is specifically "nothing else the
    engine has already found here", not merely "outside my own box".
    """
    h, w = lab.shape[:2]
    pad = BORDER_RING_PAD
    xo0, yo0 = max(0, g.x - pad), max(0, g.y - pad)
    xo1, yo1 = min(w, g.right + pad), min(h, g.bottom + pad)
    outer = lab[yo0:yo1, xo0:xo1]
    if outer.size == 0:
        return None
    mask = ~occupied[yo0:yo1, xo0:xo1]
    ring = outer.reshape(-1, 3)[mask.reshape(-1)]
    return ring if ring.size else None


def _perimeter(crop: Any, ring: int = 2) -> Any:
    """Border ring of a crop, where the background lives."""
    h, w = crop.shape[:2]
    ring = max(1, min(ring, h // 2, w // 2))
    return np.vstack([
        crop[:ring, :].reshape(-1, 3),
        crop[-ring:, :].reshape(-1, 3),
        crop[:, :ring].reshape(-1, 3),
        crop[:, -ring:].reshape(-1, 3),
    ])
