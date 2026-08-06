"""E0 -- Acquisition. Decide what counts as one stable observation.

Measures nothing, interprets nothing, corrects nothing. Its only judgement
is whether the frames it was given have settled, and it abstains when they
have not: an unstable bundle is rejected here rather than after OCR and
segmentation have already been paid for.
"""
import time
from typing import Any, Sequence

import numpy as np

from ..model import Abstention, FrameBundle, Perception
from ..pipeline import StageOutput

DEFAULT_INSTABILITY_LIMIT = 8.0


class Acquisition:
    name = "E0.acquisition"
    produces = "bundle"
    consumes = ()

    def __init__(
        self,
        frames: Sequence[Any],
        instability_limit: float = DEFAULT_INSTABILITY_LIMIT,
        captured_at: str | None = None,
    ):
        if not frames:
            raise ValueError("Acquisition needs at least one frame")
        self.frames = tuple(frames)
        self.instability_limit = instability_limit
        self.captured_at = captured_at or time.strftime("%Y%m%d-%H%M%S")

    def run(self, perception: Perception) -> StageOutput:
        instability = _instability(self.frames)
        stable = instability <= self.instability_limit

        abstentions: tuple[Abstention, ...] = ()
        if not stable:
            abstentions = (
                Abstention(
                    stage=self.name,
                    level="bundle",
                    scope_id=None,
                    reason="frames_not_settled",
                    detail={
                        "instability": round(instability, 3),
                        "limit": self.instability_limit,
                    },
                ),
            )

        bundle = FrameBundle(
            frames=self.frames,
            stable=stable,
            instability=instability,
            captured_at=self.captured_at,
        )
        return StageOutput(
            products=bundle,
            abstentions=abstentions,
            notes=(f"{len(self.frames)} frame(s)",),
            parameters={"instability_limit": self.instability_limit},
        )


def _instability(frames: Sequence[Any]) -> float:
    """Mean absolute difference between consecutive frames.

    A single frame is trivially stable -- we have no evidence it is not,
    and inventing doubt would just block the single-image debugging path
    the spec requires to keep working (§4).
    """
    if len(frames) < 2:
        return 0.0
    diffs = []
    for a, b in zip(frames, frames[1:]):
        if a.shape != b.shape:
            return float("inf")
        diffs.append(float(np.mean(np.abs(a.astype(np.int16) - b.astype(np.int16)))))
    return max(diffs)
