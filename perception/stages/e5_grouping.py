"""E5 -- Grouping. Discover which primitives form a perceptual unit.

The axis is an **output**, never an assumption. That is the whole point:
the prototype hard-coded a horizontal reading of layout, missed a
vertical sidebar entirely (0/9 real selections), and was then repaired by
bolting a second, column-shaped clustering pass beside the first. Two
hard-coded orientations is not the fix for one hard-coded orientation --
the third layout breaks it again.

Here adjacency is evaluated on both axes by the same rule, and whichever
produces a coherent, regularly-spaced run wins. A diagonal or grid layout
would simply fail to produce a regular run and be reported as ungrouped,
rather than being silently forced into the nearest supported shape.

Every threshold is expressed in units of the region's own median
primitive height. Nothing here is calibrated to a particular interface,
which is what P1/P6 require: mechanism fixed, scale self-derived.
"""
from typing import Any, Iterable

import numpy as np

from ..model import (
    Abstention,
    Group,
    Perception,
    Primitive,
    make_ids,
)
from ..pipeline import StageOutput

MIN_GROUP_SIZE = 3              # below this there is no rhythm to speak of
MAX_HEIGHT_RATIO = 0.45         # members of one unit share a text size
ALIGN_TOLERANCE = 0.55          # x units of median height
MAX_GAP = 3.2                   # x units of median height, edge to edge
MIN_OVERLAP = 0.25              # perpendicular overlap, fraction of extent
MIN_REGULARITY = 0.45


class Grouping:
    name = "E5.grouping"
    produces = "group"
    consumes = ("primitive", "descriptors", "region")

    def run(self, perception: Perception) -> StageOutput:
        if not perception.regions:
            return StageOutput(
                abstentions=(
                    Abstention(stage=self.name, level="group", scope_id=None,
                               reason="no_regions"),
                )
            )

        by_id = perception.primitives_by_id()
        candidates: list[dict[str, Any]] = []
        abstentions: list[Abstention] = []

        for region in perception.regions:
            members = [
                by_id[pid] for pid in region.primitive_ids
                if pid in by_id and by_id[pid].is_symbolic
            ]
            if len(members) < MIN_GROUP_SIZE:
                if members:
                    abstentions.append(
                        Abstention(
                            stage=self.name, level="group", scope_id=region.id,
                            reason="too_few_primitives_to_group",
                            detail={"count": len(members)},
                        )
                    )
                continue

            scale = float(np.median([m.geometry.h for m in members])) or 1.0
            found = _groups_in_region(members, scale, region.id)
            if not found:
                abstentions.append(
                    Abstention(
                        stage=self.name, level="group", scope_id=region.id,
                        reason="no_regular_arrangement_found",
                        detail={"primitives": len(members)},
                    )
                )
            candidates.extend(found)

        candidates.sort(key=lambda c: (c["box"][1], c["box"][0]))
        ids = make_ids("g", len(candidates))
        groups = tuple(
            Group(
                id=gid,
                region_id=c["region_id"],
                member_ids=tuple(c["member_ids"]),
                axis=c["axis"],
                pitch=c["pitch"],
                rhythm_regularity=c["regularity"],
                confidence=c["regularity"],
            )
            for gid, c in zip(ids, candidates)
        )

        return StageOutput(
            products=groups,
            abstentions=tuple(abstentions),
            notes=(f"{len(groups)} group(s)",),
            parameters={
                "min_group_size": MIN_GROUP_SIZE,
                "min_regularity": MIN_REGULARITY,
                "scale": "region_median_primitive_height",
            },
        )


def _groups_in_region(
    members: list[Primitive], scale: float, region_id: str
) -> list[dict[str, Any]]:
    """Try both axes with the same rule and keep whichever runs cohere.

    A primitive claimed by runs on both axes goes to the more regular one:
    an item can only belong to one rhythm, and the tighter rhythm is the
    better evidence of what it belongs to.
    """
    found: list[dict[str, Any]] = []
    for axis in ("vertical", "horizontal"):
        for component in _components(members, scale, axis):
            if len(component) < MIN_GROUP_SIZE:
                continue
            pitch, regularity = _rhythm(component, axis)
            if regularity < MIN_REGULARITY:
                continue
            found.append({
                "region_id": region_id,
                "axis": axis,
                "member_ids": [m.id for m in _ordered(component, axis)],
                "pitch": pitch,
                "regularity": regularity,
                "box": _bounds(component),
                "members": component,
            })

    return _resolve_overlaps(found)


def _components(
    members: list[Primitive], scale: float, axis: str
) -> Iterable[list[Primitive]]:
    """Connected components under the adjacency rule for one axis."""
    n = len(members)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    for i in range(n):
        for j in range(i + 1, n):
            if _adjacent(members[i], members[j], scale, axis):
                union(i, j)

    buckets: dict[int, list[Primitive]] = {}
    for i, member in enumerate(members):
        buckets.setdefault(find(i), []).append(member)
    return buckets.values()


def _adjacent(a: Primitive, b: Primitive, scale: float, axis: str) -> bool:
    ga, gb = a.geometry, b.geometry

    # Same visual size. A caption under a menu entry is not a menu entry,
    # and this is what keeps a description line out of the item's class --
    # the contamination the prototype documented as a known limitation.
    if abs(ga.h - gb.h) / max(ga.h, gb.h, 1) > MAX_HEIGHT_RATIO:
        return False

    if axis == "vertical":
        aligned = (
            abs(ga.x - gb.x) <= ALIGN_TOLERANCE * scale
            or abs(ga.cx - gb.cx) <= ALIGN_TOLERANCE * scale
            or abs(ga.right - gb.right) <= ALIGN_TOLERANCE * scale
        )
        overlap = _overlap(ga.x, ga.right, gb.x, gb.right)
        extent = min(ga.w, gb.w)
        gap = max(ga.y, gb.y) - min(ga.bottom, gb.bottom)
    else:
        aligned = (
            abs(ga.y - gb.y) <= ALIGN_TOLERANCE * scale
            or abs(ga.cy - gb.cy) <= ALIGN_TOLERANCE * scale
            or abs(ga.bottom - gb.bottom) <= ALIGN_TOLERANCE * scale
        )
        overlap = _overlap(ga.y, ga.bottom, gb.y, gb.bottom)
        extent = min(ga.h, gb.h)
        gap = max(ga.x, gb.x) - min(ga.right, gb.right)

    if not aligned:
        return False
    if overlap < MIN_OVERLAP * max(1, extent):
        return False
    return gap <= MAX_GAP * scale


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _ordered(members: list[Primitive], axis: str) -> list[Primitive]:
    key = (lambda m: (m.geometry.cy, m.geometry.cx)) if axis == "vertical" \
        else (lambda m: (m.geometry.cx, m.geometry.cy))
    return sorted(members, key=key)


def _rhythm(members: list[Primitive], axis: str) -> tuple[float | None, float]:
    """Pitch and how regular it is, on a 0..1 scale.

    Regularity is measured against the pitch itself, so it means the same
    thing on a 4K photo and a 720p one.
    """
    ordered = _ordered(members, axis)
    centres = [
        (m.geometry.cy if axis == "vertical" else m.geometry.cx) for m in ordered
    ]
    steps = np.diff(np.array(centres, dtype=float))
    if len(steps) == 0:
        return None, 0.0
    pitch = float(np.median(steps))
    if pitch <= 1e-6:
        return None, 0.0
    deviation = float(np.median(np.abs(steps - pitch)))
    return pitch, float(max(0.0, 1.0 - deviation / pitch))


def _bounds(members: list[Primitive]) -> tuple[int, int, int, int]:
    xs = [m.geometry.x for m in members]
    ys = [m.geometry.y for m in members]
    return (min(xs), min(ys), max(m.geometry.right for m in members),
            max(m.geometry.bottom for m in members))


def _resolve_overlaps(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One primitive, one rhythm. Ties go to the more regular group, then
    to the larger one -- both deterministic, so F7 holds.
    """
    ranked = sorted(found, key=lambda c: (-c["regularity"], -len(c["member_ids"])))
    taken: set[str] = set()
    kept: list[dict[str, Any]] = []
    for candidate in ranked:
        remaining = [m for m in candidate["member_ids"] if m not in taken]
        if len(remaining) < MIN_GROUP_SIZE:
            continue
        candidate = dict(candidate, member_ids=remaining)
        taken.update(remaining)
        kept.append(candidate)
    return kept
