"""Interface Perception Engine -- implementation of PERCEPTION_PIPELINE_SPEC.

Converts an observed surface into a structured description of the
interface: what is on it, how it is organised, and which elements deviate
from their peers. It decides nothing about meaning. Cognition consumes
the contract afterwards and is never consulted during perception.

Usage:

    from perception import perceive
    result = perceive(frames=[image])
    result.contract["regions"]

The default pipeline runs every stage at the v1 depth of the maturity
table (§6): canonical geometry only in conditioning, a subset of state
channels, structural types without behavioural claims. Deeper stages are
substitutions, not rewrites -- each stage is defined by its contract
(§8), so replacing one is a file swap.
"""
from ocr import DEFAULT_ENGINE

from .model import (
    Abstention,
    Descriptors,
    EquivalenceClass,
    FrameBundle,
    Geometry,
    Group,
    Perception,
    Primitive,
    Region,
    ScreenIdentity,
    State,
    StructuralType,
    Surface,
)
from .pipeline import (
    ContractViolation,
    PipelineResult,
    Stage,
    StageOutput,
    describe_pipeline,
    run_pipeline,
    validate_pipeline,
)
from .stages import (
    Acquisition,
    Characterisation,
    Conditioning,
    Equivalence,
    Extraction,
    Grouping,
    Identity,
    Regionalisation,
    Serialisation,
    StateInference,
    Typing,
)

__all__ = [
    "perceive",
    "default_pipeline",
    "Perception",
    "PipelineResult",
    "ContractViolation",
    "describe_pipeline",
    "run_pipeline",
    "validate_pipeline",
    "Stage",
    "StageOutput",
    "Abstention",
    "Descriptors",
    "EquivalenceClass",
    "FrameBundle",
    "Geometry",
    "Group",
    "Primitive",
    "Region",
    "ScreenIdentity",
    "State",
    "StructuralType",
    "Surface",
]


def default_pipeline(
    frames,
    engine: str = DEFAULT_ENGINE,
    rectify: bool = True,
    view: str = "digest",
    captured_at: str | None = None,
    ocr_votes: int = 1,
) -> list:
    """The eleven stages in order, at v1 depth."""
    return [
        Acquisition(frames=frames, captured_at=captured_at),
        Conditioning(rectify=rectify),
        Extraction(engine=engine, ocr_votes=ocr_votes),
        Characterisation(),
        Regionalisation(),
        Grouping(),
        Equivalence(),
        StateInference(),
        Typing(),
        Identity(),
        Serialisation(view=view),
    ]


def perceive(
    frames,
    engine: str = DEFAULT_ENGINE,
    rectify: bool = True,
    view: str = "digest",
    captured_at: str | None = None,
    trace: bool = False,
    ocr_votes: int = 1,
) -> PipelineResult:
    """Run the default pipeline over one or more frames of a single view.

    More than one frame is normal, not special: §4 keeps temporal evidence
    strictly corroborating, so a bundle of one produces a valid result and
    extra frames only raise confidence. `ocr_votes` is what actually spends
    the extra frames on OCR: 1 reads only the representative frame (today's
    behaviour, unchanged); >1 re-reads each detected text box from up to
    `ocr_votes - 1` of the bundle's other frames and votes on content (see
    `perception/stages/e2_extraction.py`). Needs `len(frames) >= ocr_votes`
    to have full effect -- a shorter bundle just yields fewer votes, not an
    error.
    """
    stages = default_pipeline(
        frames=frames, engine=engine, rectify=rectify, view=view,
        captured_at=captured_at, ocr_votes=ocr_votes,
    )
    return run_pipeline(stages, trace=trace)
