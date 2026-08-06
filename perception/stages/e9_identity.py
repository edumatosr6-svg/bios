"""E9 -- Identity. Is this the same screen as before?

Derived from content and structure, never from appearance. Appearance
varies with every observation -- lighting, angle, exposure -- while the
set of labels on a screen and the shape of its layout do not. A
fingerprint built on colour would report a new screen every time a cloud
passed the window.

The engine says "this is the screen with identity X". It does **not** say
"this is the Security page". Naming is cognition (§E9). What identity
buys is that the cognition layer can build a navigation map over time
without anyone writing that map by hand: the same screen reached twice
gets the same id, so "I have been here" becomes answerable.
"""
import hashlib
import re

from ..model import Perception, ScreenIdentity
from ..pipeline import StageOutput

MIN_TOKEN_LENGTH = 2
TITLE_BAND = 0.16               # top fraction of the surface


class Identity:
    name = "E9.identity"
    produces = "identity"
    consumes = ("primitive", "region", "group", "type")

    def run(self, perception: Perception) -> StageOutput:
        symbolic = [p for p in perception.primitives if p.is_symbolic and p.content]
        if not symbolic:
            return StageOutput(products=None)

        tokens = sorted({
            token
            for primitive in symbolic
            for token in _normalise(primitive.content)
        })
        content_fp = _digest("|".join(tokens))

        # Structure: how many groups of what shape and size. Independent
        # of what any of them say, so a screen keeps its identity when OCR
        # misreads a word.
        shape = sorted(
            f"{g.axis}:{g.cardinality}" for g in perception.groups
        )
        structure_fp = _digest(f"r{len(perception.regions)}|" + "|".join(shape))

        identity = ScreenIdentity(
            screen_id=_digest(content_fp + structure_fp)[:16],
            title_text=_title(perception, symbolic),
            content_fingerprint=content_fp[:16],
            structure_fingerprint=structure_fp[:16],
            confidence=0.9 if len(tokens) >= 8 else 0.5,
        )
        return StageOutput(
            products=identity,
            notes=(f"{len(tokens)} content tokens",),
            parameters={"title_band": TITLE_BAND},
        )


def _normalise(text: str) -> list[str]:
    """Lowercase word tokens. Tolerates the punctuation and stray glyphs
    OCR invents around real words.
    """
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return [t for t in cleaned.split() if len(t) >= MIN_TOKEN_LENGTH]


def _title(perception: Perception, symbolic) -> str | None:
    surface = perception.surface
    if surface is None:
        return None
    band = TITLE_BAND * surface.height
    candidates = [p for p in symbolic if p.geometry.cy <= band]
    if not candidates:
        return None
    # Tallest text in the top band: a title is set larger than its page.
    best = max(candidates, key=lambda p: (p.geometry.h, -p.geometry.x))
    return best.content


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
