"""The runner, and the mechanical enforcement of the flow rules (§2).

A specification rule that is only written down gets violated the first
time someone is in a hurry. These are the ones worth making executable:

* **F1/F2** -- every stage declares the levels it consumes and the level
  it produces, and the runner refuses to build a pipeline where a stage
  consumes its own level or anything above it. Deriving state straight
  from primitives is not "discouraged" here, it raises at construction
  time, before a single pixel is read.

* **F4** -- the runner, not the stage, writes the provenance record, so a
  stage cannot forget to.

* **F5** -- products are folded into a fresh `Perception`; no stage can
  overwrite a lower level even by accident, because it never receives a
  mutable handle to one.

* **F7** -- the effective parameters of every stage are captured into the
  provenance, so a run can be reproduced from its own output.

What the runner deliberately does *not* do is recover from a stage's
abstention. Abstention propagates (F3): if regionalisation cannot
establish context, grouping receives no regions and will itself abstain.
That cascade is the intended behaviour, not a failure to handle.
"""
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .model import (
    LEVEL_INDEX,
    Abstention,
    Perception,
    StageRecord,
)

# Which field of Perception each level lands in, and whether the level
# holds one object or many.
_LEVEL_FIELD: Mapping[str, tuple[str, str]] = {
    "bundle": ("bundle", "single"),
    "surface": ("surface", "single"),
    "primitive": ("primitives", "tuple"),
    "descriptors": ("descriptors", "mapping"),
    "region": ("regions", "tuple"),
    "group": ("groups", "tuple"),
    "class": ("classes", "tuple"),
    "state": ("states", "tuple"),
    "type": ("types", "tuple"),
    "identity": ("identity", "single"),
    "contract": ("", "external"),
}


@dataclass(frozen=True, slots=True)
class StageOutput:
    """What a stage hands back. Never a mutated input."""
    products: Any = None
    abstentions: tuple[Abstention, ...] = ()
    notes: tuple[str, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class Stage(Protocol):
    """A stage is defined by its contract, not its implementation (F6).

    Swapping how a stage works, without changing what it consumes and
    produces, is not an architectural change and needs no spec revision.
    """
    name: str
    produces: str
    consumes: tuple[str, ...]

    def run(self, perception: Perception) -> StageOutput: ...


class ContractViolation(Exception):
    """Raised when a pipeline would break a flow rule. Construction-time,
    never run-time -- an illegal pipeline should not be buildable.
    """


def validate_stage(stage: Stage) -> None:
    if stage.produces not in LEVEL_INDEX:
        raise ContractViolation(
            f"{stage.name}: unknown produced level {stage.produces!r}"
        )
    produced = LEVEL_INDEX[stage.produces]
    for consumed in stage.consumes:
        if consumed not in LEVEL_INDEX:
            raise ContractViolation(
                f"{stage.name}: unknown consumed level {consumed!r}"
            )
        if LEVEL_INDEX[consumed] >= produced:
            raise ContractViolation(
                f"{stage.name} consumes {consumed!r} to produce "
                f"{stage.produces!r}. A stage may only consume levels "
                f"strictly below the one it produces (F1/F2)."
            )


def validate_pipeline(stages: Sequence[Stage]) -> None:
    """Every stage legal on its own, and no stage consuming a level that
    nothing earlier has produced.
    """
    available: set[str] = set()
    for stage in stages:
        validate_stage(stage)
        for consumed in stage.consumes:
            if consumed not in available:
                raise ContractViolation(
                    f"{stage.name} consumes {consumed!r}, which no earlier "
                    f"stage produces."
                )
        available.add(stage.produces)


@dataclass(frozen=True, slots=True)
class PipelineResult:
    perception: Perception
    contract: Mapping[str, Any] | None = None

    @property
    def abstentions(self) -> tuple[Abstention, ...]:
        return self.perception.abstentions


def _fold(perception: Perception, stage: Stage, output: StageOutput) -> Perception:
    field_name, arity = _LEVEL_FIELD[stage.produces]
    updates: dict[str, Any] = {}

    if arity == "single":
        if output.products is not None:
            updates[field_name] = output.products
    elif arity == "tuple":
        products = tuple(output.products or ())
        _assert_unique_ids(stage, products)
        updates[field_name] = products
    elif arity == "mapping":
        updates[field_name] = dict(output.products or {})
    # "external" (the contract) is returned to the caller, not accumulated.

    if output.abstentions:
        updates["abstentions"] = perception.abstentions + tuple(output.abstentions)

    updates["provenance"] = perception.provenance + (
        StageRecord(
            stage=stage.name,
            produces=stage.produces,
            consumes=tuple(stage.consumes),
            n_products=_count(output.products),
            n_abstentions=len(output.abstentions),
            parameters=dict(output.parameters),
            notes=tuple(output.notes),
        ),
    )
    return perception.merge(**updates)


def _assert_unique_ids(stage: Stage, products: Sequence[Any]) -> None:
    ids = [getattr(p, "id", None) for p in products]
    ids = [i for i in ids if i is not None]
    if len(ids) != len(set(ids)):
        raise ContractViolation(f"{stage.name} produced duplicate object ids")


def _count(products: Any) -> int:
    if products is None:
        return 0
    if isinstance(products, (str, bytes)):
        return 1
    try:
        return len(products)
    except TypeError:
        return 1


def run_pipeline(
    stages: Sequence[Stage],
    perception: Perception | None = None,
    trace: bool = False,
) -> PipelineResult:
    """Run stages in order, folding each product into a fresh Perception."""
    validate_pipeline(stages)

    current = perception or Perception()
    contract: Mapping[str, Any] | None = None

    for stage in stages:
        output = stage.run(current)
        if stage.produces == "contract":
            contract = output.products
            current = _fold(current, stage, output)
        else:
            current = _fold(current, stage, output)
        if trace:
            print(
                f"  {stage.name:<20} -> {stage.produces:<12} "
                f"{_count(output.products):>4} products, "
                f"{len(output.abstentions):>2} abstentions"
            )

    return PipelineResult(perception=current, contract=contract)


def describe_pipeline(stages: Sequence[Stage]) -> str:
    lines = ["level          stage", "-" * 46]
    for stage in stages:
        consumed = ", ".join(stage.consumes) or "-"
        lines.append(f"{stage.produces:<14} {stage.name:<22} <- {consumed}")
    return "\n".join(lines)
