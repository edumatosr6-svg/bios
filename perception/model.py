"""The objects of PERCEPTION_PIPELINE_SPEC §1, as immutable records.

This module answers the question the spec deliberately left open: what is
the object *in memory*. Three decisions, each traceable to a spec rule:

1. **Immutable, id-addressed records** rather than mutable objects holding
   direct references. Every object carries a stable id and refers to other
   objects by id, never by pointer. The whole perception is therefore a
   DAG whose edges only ever point *downward* (a Group names Primitives, a
   Primitive can't name a Group). That makes F1 (unidirectionality) and F2
   (no level skipping) structural rather than aspirational: a stage
   physically cannot reach upward because the upward reference does not
   exist.

   The prototype's `selection.py` did the opposite -- `annotate_selection`
   mutated the OCR blocks in place, adding `highlighted`/`region` onto the
   very dicts it was reading. That works, but it means the input to a
   stage is destroyed by running it, there is no way to compare before
   and after, and nothing prevents a later step from quietly depending on
   an earlier step's mutation. Immutability removes the whole class.

2. **Products accumulate; nothing is replaced.** `Perception` grows one
   field per stage and keeps everything below (F5). The contract's compact
   view is then a pure projection of what is already in memory, never a
   recomputation -- which is exactly what §E10 requires and the only way
   the audit view and the cognition view cannot drift apart.

3. **Invalid is not absent.** `Descriptors.get` returns None for a
   descriptor that was measured but is not trustworthy, so a downstream
   stage that forgets to check validity gets nothing rather than a
   plausible-looking number. §E3 states this as a requirement; here it is
   enforced by the accessor instead of by reviewer discipline.

Nothing in this module knows what a BIOS is, what colour means, or how any
measurement is taken.
"""
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

# Flow levels, ordered. The middle of this list is the spec's object
# chain (§1); `bundle` and `surface` sit below it as the inputs the chain
# is built from, and `contract` above it as the projection out. The
# pipeline runner uses this ordering to reject a stage that tries to
# consume a level at or above the one it produces (F2).
LEVELS: tuple[str, ...] = (
    "bundle",
    "surface",
    "primitive",
    "descriptors",
    "region",
    "group",
    "class",
    "state",
    "type",
    "identity",
    "contract",
)

LEVEL_INDEX: Mapping[str, int] = {name: i for i, name in enumerate(LEVELS)}


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Geometry:
    """Axis-aligned box in canonical surface coordinates.

    "Canonical" matters: these numbers are only comparable between
    elements because E1 put them in a common frame. Geometry measured on a
    raw observation is not interchangeable with this.
    """
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def area(self) -> int:
        return max(0, self.w) * max(0, self.h)

    def intersection_area(self, other: "Geometry") -> int:
        dx = min(self.right, other.right) - max(self.x, other.x)
        dy = min(self.bottom, other.bottom) - max(self.y, other.y)
        return dx * dy if dx > 0 and dy > 0 else 0

    def as_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


# --------------------------------------------------------------------------
# Provenance and abstention (F3, F4)
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Abstention:
    """A declared refusal to decide (F3).

    Carried as *content* all the way into the contract, because the
    cognition layer has to be able to tell "there is no selection here"
    apart from "the selection could not be determined". §E10 calls
    conflating those two the most dangerous failure of the engine: they
    call for opposite actions.
    """
    stage: str
    level: str
    scope_id: str | None
    reason: str
    detail: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "level": self.level,
            "scope_id": self.scope_id,
            "reason": self.reason,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True, slots=True)
class StageRecord:
    """What a stage did, kept so any product can be traced back (F4)."""
    stage: str
    produces: str
    consumes: tuple[str, ...]
    n_products: int
    n_abstentions: int
    parameters: Mapping[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "produces": self.produces,
            "consumes": list(self.consumes),
            "n_products": self.n_products,
            "n_abstentions": self.n_abstentions,
            "parameters": dict(self.parameters),
            "notes": list(self.notes),
        }


# --------------------------------------------------------------------------
# L0 / L1 -- surface and primitives
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FrameBundle:
    """E0's product: the observations that make up one stable view.

    Carrying more than one frame is what later allows temporal evidence,
    but §4 makes that strictly corroborating: every stage must produce a
    valid result from a single frame, so a bundle of one is normal and
    not a degraded case.
    """
    frames: tuple[Any, ...]
    stable: bool
    instability: float = 0.0
    captured_at: str | None = None

    @property
    def representative(self) -> Any:
        """The frame everything is measured on. Last of a stable run: the
        settled view, after any transition has finished.
        """
        return self.frames[-1]


@dataclass(frozen=True, slots=True)
class Surface:
    """E1's product: one observation in a canonical frame.

    `transform` is the mapping applied to get here, and `rectified` says
    whether it was a real rectification or an identity pass-through. The
    difference is not cosmetic -- when rectification is skipped, geometric
    descriptors are still usable but their cross-element comparability is
    weaker, and that has to be visible downstream rather than assumed.
    """
    image: Any                      # canonical pixels (h, w, 3)
    width: int
    height: int
    rectified: bool
    transform: tuple[tuple[float, ...], ...] | None
    quality: Mapping[str, float] = field(default_factory=dict)
    frames_used: int = 1


@dataclass(frozen=True, slots=True)
class Primitive:
    """E2's product: something localisable, before any interpretation.

    A Primitive has geometry and (if symbolic) content. It deliberately
    has no membership, no role and no state: per §1.1 those are not
    properties an isolated primitive can carry, so asking whether a
    Primitive is selected is a malformed question and the type refuses to
    represent it.

    `source_group` exists only to record how the producing source happened
    to bundle its output. §E2's non-contamination rule forbids using it as
    structure -- grouping belongs to E4-E6. It is kept because throwing
    away provenance would violate F4, not because anyone may read it.
    """
    id: str
    kind: str                       # "symbolic" | "structural"
    source: str                     # which source produced it
    geometry: Geometry
    content: str | None = None
    confidence: float = 1.0
    shape: str | None = None        # structural only: "rule" | "filled_rect" | ...
    source_group: str | None = None

    @property
    def is_symbolic(self) -> bool:
        return self.kind == "symbolic"


@dataclass(frozen=True, slots=True)
class Descriptors:
    """E3's product for one primitive.

    `invalid` names descriptors that were measured but must not be
    trusted. `get` honours that automatically so a caller cannot use one
    by forgetting to check -- the spec requires invalid descriptors to
    stay out of downstream decisions, and it is cheaper to enforce here
    than to audit every call site.
    """
    primitive_id: str
    values: Mapping[str, Any] = field(default_factory=dict)
    invalid: frozenset[str] = frozenset()

    def get(self, name: str, default: Any = None) -> Any:
        if name in self.invalid:
            return default
        return self.values.get(name, default)

    def is_valid(self, *names: str) -> bool:
        return all(n in self.values and n not in self.invalid for n in names)


# --------------------------------------------------------------------------
# L3 / L4 / L5 -- region, group, equivalence class
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Region:
    """E4's product: a bounded area sharing one visual context.

    Not a component -- the scope within which comparing is legitimate.
    """
    id: str
    geometry: Geometry
    primitive_ids: tuple[str, ...]
    parent_id: str | None = None
    confidence: float = 1.0
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Group:
    """E5's product: a perceptual unit inside a region.

    `axis` is an output of perception, never an input assumption. The
    prototype's failure on a vertical BIOS menu came from the opposite
    choice: row clustering hard-coded a horizontal reading of "region",
    so a vertical menu could not be seen as a group at all, and its items
    ended up compared against the whole screen. Any stage that assumes an
    orientation is wrong by construction (§E5).
    """
    id: str
    region_id: str
    member_ids: tuple[str, ...]
    axis: str                       # "vertical" | "horizontal" | "none"
    pitch: float | None = None
    rhythm_regularity: float = 0.0
    confidence: float = 1.0

    @property
    def cardinality(self) -> int:
        return len(self.member_ids)


@dataclass(frozen=True, slots=True)
class EquivalenceClass:
    """E6's product, and the central object of the whole engine (§1.1).

    The reference population against which a state is defined. A class
    that cannot serve as a reference says so explicitly rather than being
    silently dropped: "too few members to compare" is information the
    cognition layer needs, not an internal detail.
    """
    id: str
    group_id: str
    region_id: str
    member_ids: tuple[str, ...]
    role: str                       # structural role shared by members
    usable_as_reference: bool = True
    reason_unusable: str | None = None

    @property
    def size(self) -> int:
        return len(self.member_ids)


# --------------------------------------------------------------------------
# L6 -- state
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class State:
    """E7's product, and literally the spec's formal definition:

        estado = (elemento, classe, canal, magnitude, confianca)

    A State cannot be constructed without naming the class it is relative
    to, which is the type-level statement of "sem classe nao existe
    estado". `channels` is plural because independent channels are
    evaluated separately and then combined, and which ones agreed is
    evidence the cognition layer is entitled to see (F4).
    """
    element_id: str
    class_id: str
    name: str                       # "selected" | "disabled" | ...
    channels: tuple[str, ...]
    magnitude: float
    confidence: float
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "class_id": self.class_id,
            "name": self.name,
            "channels": list(self.channels),
            "magnitude": round(float(self.magnitude), 4),
            "confidence": round(float(self.confidence), 4),
            "evidence": {
                k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in self.evidence.items()
            },
        }


# --------------------------------------------------------------------------
# L7 / L8 -- structural type and screen identity
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class StructuralType:
    """E8's product, in two strictly separated parts.

    `structural` is a fact decidable from the surface. `semantic_hint` is
    an opinion with a confidence, and the cognition layer may discard it
    without losing the fact. Collapsing the two would put cognition inside
    perception, which is the one thing the architecture exists to prevent.
    """
    target_id: str                  # region or group id
    structural: str
    attributes: Mapping[str, Any] = field(default_factory=dict)
    semantic_hint: str | None = None
    hint_confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class ScreenIdentity:
    """E9's product: whether this is a screen already seen.

    Derived from content and structure, not appearance -- appearance
    varies with the observation, content and structure do not. The engine
    says "this is the screen with identity X"; naming that screen is
    cognition (§E9).
    """
    screen_id: str
    title_text: str | None
    content_fingerprint: str
    structure_fingerprint: str
    confidence: float = 1.0


# --------------------------------------------------------------------------
# The accumulator
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Perception:
    """Every stage's product, accumulated and never overwritten (F5).

    Read-only by construction: a stage receives one of these and returns
    new products, and only the runner folds them in. Two stages can never
    fight over the same field because neither can write it.
    """
    bundle: FrameBundle | None = None
    surface: Surface | None = None
    primitives: tuple[Primitive, ...] = ()
    descriptors: Mapping[str, Descriptors] = field(default_factory=dict)
    regions: tuple[Region, ...] = ()
    groups: tuple[Group, ...] = ()
    classes: tuple[EquivalenceClass, ...] = ()
    states: tuple[State, ...] = ()
    types: tuple[StructuralType, ...] = ()
    identity: ScreenIdentity | None = None
    abstentions: tuple[Abstention, ...] = ()
    provenance: tuple[StageRecord, ...] = ()

    # -- lookups ---------------------------------------------------------

    def primitive(self, pid: str) -> Primitive | None:
        for p in self.primitives:
            if p.id == pid:
                return p
        return None

    def primitives_by_id(self) -> dict[str, Primitive]:
        return {p.id: p for p in self.primitives}

    def desc(self, pid: str) -> Descriptors:
        return self.descriptors.get(pid) or Descriptors(primitive_id=pid)

    def region(self, rid: str) -> Region | None:
        for r in self.regions:
            if r.id == rid:
                return r
        return None

    def group(self, gid: str) -> Group | None:
        for g in self.groups:
            if g.id == gid:
                return g
        return None

    def klass(self, cid: str) -> EquivalenceClass | None:
        for c in self.classes:
            if c.id == cid:
                return c
        return None

    def states_of(self, element_id: str) -> tuple[State, ...]:
        return tuple(s for s in self.states if s.element_id == element_id)

    def type_of(self, target_id: str) -> StructuralType | None:
        for t in self.types:
            if t.target_id == target_id:
                return t
        return None

    def merge(self, **updates: Any) -> "Perception":
        return replace(self, **updates)


def make_ids(prefix: str, count: int) -> list[str]:
    """Stable, readable ids. Determinism (F7) comes from the caller
    ordering its products before asking for ids, not from this function.
    """
    width = max(3, len(str(count)))
    return [f"{prefix}{i + 1:0{width}d}" for i in range(count)]


def sorted_by_position(items: Sequence[Any], key=lambda o: o.geometry) -> list[Any]:
    """Reading order: top to bottom, then left to right.

    Every stage sorts its products through this before ids are assigned,
    so the same input yields byte-identical output (F7).
    """
    return sorted(items, key=lambda o: (key(o).y, key(o).x, key(o).w, key(o).h))
