"""The eleven stages of PERCEPTION_PIPELINE_SPEC §3.

One module per stage, because §8 defines a stage by its contract rather
than its implementation (F6): swapping how any one of these works,
without changing what it consumes and produces, is not an architectural
change and needs no spec revision. Keeping them in separate modules is
what makes that substitution a file swap instead of surgery.
"""
from .e0_acquisition import Acquisition
from .e1_conditioning import Conditioning
from .e2_extraction import Extraction
from .e3_characterization import Characterisation
from .e4_regionalization import Regionalisation
from .e5_grouping import Grouping
from .e6_equivalence import Equivalence
from .e7_state import StateInference
from .e8_typing import Typing
from .e9_identity import Identity
from .e10_serialization import Serialisation

__all__ = [
    "Acquisition",
    "Conditioning",
    "Extraction",
    "Characterisation",
    "Regionalisation",
    "Grouping",
    "Equivalence",
    "StateInference",
    "Typing",
    "Identity",
    "Serialisation",
]
