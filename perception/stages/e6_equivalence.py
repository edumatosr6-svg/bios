"""E6 -- Equivalence. Partition a group into what is actually comparable.

The smallest stage, and the most expensive one to skip. Without it,
members playing different structural roles end up compared against each
other and the resulting "state" is noise wearing the shape of signal.

Concretely: the prototype documented a limitation where a submenu entry's
adjacent description line contaminated the comparison. That is not a
threshold problem. A description line is a different role -- different
size, different alignment, different purpose -- and belongs in a
different reference population. Once the roles are separated, the entry
is compared against other entries and the description against other
descriptions, and the contamination has nowhere to come from.

A class that cannot serve as a reference says so explicitly. "Too few
members to compare" is information the cognition layer needs, not an
internal detail to swallow: it is the difference between "nothing is
selected here" and "I could not tell", which §E10 calls the most
dangerous confusion in the engine.
"""
import numpy as np

from ..model import (
    Abstention,
    EquivalenceClass,
    Perception,
    make_ids,
)
from ..pipeline import StageOutput

MIN_CLASS_SIZE = 3              # below this there is no population to deviate from
SIZE_GAP = 0.34                 # x median height: split sizes further apart than this
ALIGN_GAP = 0.7                 # x median height: split alignments further apart


class Equivalence:
    name = "E6.equivalence"
    produces = "class"
    consumes = ("primitive", "descriptors", "region", "group")

    def run(self, perception: Perception) -> StageOutput:
        if not perception.groups:
            return StageOutput(
                abstentions=(
                    Abstention(stage=self.name, level="class", scope_id=None,
                               reason="no_groups"),
                )
            )

        by_id = perception.primitives_by_id()
        partitions: list[dict] = []
        abstentions: list[Abstention] = []

        for group in perception.groups:
            members = [by_id[m] for m in group.member_ids if m in by_id]
            if not members:
                continue
            for role, role_members in _by_role(members, group.axis):
                partitions.append({
                    "group": group,
                    "role": role,
                    "member_ids": [m.id for m in role_members],
                    "anchor": (role_members[0].geometry.y, role_members[0].geometry.x),
                })

        partitions.sort(key=lambda p: (p["anchor"], p["role"]))
        ids = make_ids("c", len(partitions))

        classes = []
        for cid, part in zip(ids, partitions):
            size = len(part["member_ids"])
            usable = size >= MIN_CLASS_SIZE
            reason = None if usable else "too_few_members_to_compare"
            classes.append(
                EquivalenceClass(
                    id=cid,
                    group_id=part["group"].id,
                    region_id=part["group"].region_id,
                    member_ids=tuple(part["member_ids"]),
                    role=part["role"],
                    usable_as_reference=usable,
                    reason_unusable=reason,
                )
            )
            if not usable:
                abstentions.append(
                    Abstention(
                        stage=self.name, level="class", scope_id=cid,
                        reason=reason,
                        detail={"size": size, "minimum": MIN_CLASS_SIZE},
                    )
                )

        return StageOutput(
            products=tuple(classes),
            abstentions=tuple(abstentions),
            notes=(f"{len(classes)} class(es)",),
            parameters={"min_class_size": MIN_CLASS_SIZE},
        )


def _by_role(members, axis: str):
    """Structural role, v1: shared size and shared alignment edge.

    Both are properties of how an interface lays out things that mean the
    same kind of thing, and neither needs to know what the interface is
    about.

    Grouping is by **gap**, not by rounding a value into a fixed band.
    Banding looks equivalent and is not: two items three pixels apart
    straddle a band boundary and land in different classes, which on real
    photos happens constantly because OCR box edges jitter. Measured on
    the Positivo fixtures, that split the actually-selected entry into a
    class of one -- where, having no peers, it could not be compared and
    so could never be found. Splitting only where a real gap exists is
    stable under that jitter.
    """
    scale = float(np.median([m.geometry.h for m in members])) or 1.0

    align_of = (lambda m: float(m.geometry.x)) if axis == "vertical" \
        else (lambda m: float(m.geometry.y))
    align_clusters = _cluster(members, align_of, ALIGN_GAP * scale)

    edge = "left" if axis == "vertical" else "top"
    prefix = "v" if axis == "vertical" else "h"

    buckets: list[tuple[str, list]] = []
    for a_index, aligned in enumerate(align_clusters):
        # Height is a noisy proxy for text size: descenders and
        # ascenders move the box by several pixels on identical text, so
        # the tolerance has to be looser than the thing it measures.
        for s_index, sized in enumerate(
            _cluster(aligned, lambda m: float(m.geometry.h), SIZE_GAP * scale)
        ):
            role = f"{prefix}:{edge}{a_index}:size{s_index}"
            buckets.append((role, sorted(sized, key=lambda m: (m.geometry.y, m.geometry.x))))

    for role, group in buckets:
        yield role, group


def _cluster(members, value_of, max_gap: float):
    """One-dimensional clustering: a new cluster starts only where the
    sorted values leave a gap wider than `max_gap`.
    """
    if not members:
        return []
    ordered = sorted(members, key=value_of)
    clusters = [[ordered[0]]]
    for previous, current in zip(ordered, ordered[1:]):
        if value_of(current) - value_of(previous) > max_gap:
            clusters.append([])
        clusters[-1].append(current)
    return clusters
