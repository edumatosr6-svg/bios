"""E10 -- Serialisation. Communicate, including what was not decided.

The only stage that may not abstain: something must come out.

Two views from one run. The full view omits nothing and exists for audit
and regression. The compact view is what the cognition layer reads, and
is a **projection** of the full one -- never a second computation. If it
were recomputed, the two could disagree and the audit would stop auditing
what actually ran.

Abstentions are content, not absence. A caller has to be able to tell
"nothing is selected here" from "I could not tell", because those call
for opposite actions: the first means move on, the second means look
again. Dropping the abstention list would collapse the two into silence.
"""
from typing import Any

from ..model import Perception
from ..pipeline import StageOutput

SPEC_VERSION = "0.1"


class Serialisation:
    name = "E10.serialisation"
    produces = "contract"
    consumes = ("primitive", "descriptors", "region", "group", "class",
                "state", "type", "identity")

    def __init__(self, view: str = "digest"):
        if view not in ("digest", "full", "both"):
            raise ValueError("view must be 'digest', 'full' or 'both'")
        self.view = view

    def run(self, perception: Perception) -> StageOutput:
        full = _full(perception)
        if self.view == "full":
            contract = full
        elif self.view == "digest":
            contract = _digest(perception, full)
        else:
            contract = {"digest": _digest(perception, full), "full": full}

        return StageOutput(
            products=contract,
            notes=(f"view={self.view}",),
            parameters={"spec_version": SPEC_VERSION, "view": self.view},
        )


def _digest(perception: Perception, full: dict[str, Any]) -> dict[str, Any]:
    """Projection of `full` -- structure, content, state, uncertainty."""
    by_id = perception.primitives_by_id()
    states_by_element: dict[str, list] = {}
    for state in perception.states:
        states_by_element.setdefault(state.element_id, []).append(state)

    regions: list[dict[str, Any]] = []
    for region in perception.regions:
        groups: list[dict[str, Any]] = []
        for group in perception.groups:
            if group.region_id != region.id:
                continue
            typing = perception.type_of(group.id)
            elements = []
            for member_id in group.member_ids:
                primitive = by_id.get(member_id)
                if primitive is None:
                    continue
                elements.append({
                    "id": member_id,
                    "text": primitive.content,
                    "state": [
                        {
                            "name": s.name,
                            "confidence": round(s.confidence, 3),
                            "channels": list(s.channels),
                        }
                        for s in states_by_element.get(member_id, ())
                    ],
                })
            groups.append({
                "id": group.id,
                "structural_type": typing.structural if typing else "Unknown",
                "axis": group.axis,
                "cardinality": group.cardinality,
                "semantic_hint": (
                    {"value": typing.semantic_hint,
                     "confidence": round(typing.hint_confidence, 3)}
                    if typing and typing.semantic_hint else None
                ),
                "elements": elements,
            })

        region_type = perception.type_of(region.id)
        regions.append({
            "id": region.id,
            "structural_type": region_type.structural if region_type else "Region",
            "geometry": region.geometry.as_dict(),
            "groups": groups,
        })

    identity = perception.identity
    return {
        "spec_version": SPEC_VERSION,
        "screen": {
            "screen_id": identity.screen_id if identity else None,
            "title_text": identity.title_text if identity else None,
            "confidence": round(identity.confidence, 3) if identity else 0.0,
            "quality": dict(perception.surface.quality) if perception.surface else {},
            "rectified": perception.surface.rectified if perception.surface else False,
        },
        "regions": regions,
        # Content, not absence. See the module docstring.
        "abstentions": [a.as_dict() for a in perception.abstentions],
    }


def _full(perception: Perception) -> dict[str, Any]:
    return {
        "spec_version": SPEC_VERSION,
        "surface": (
            {
                "width": perception.surface.width,
                "height": perception.surface.height,
                "rectified": perception.surface.rectified,
                "quality": dict(perception.surface.quality),
                "frames_used": perception.surface.frames_used,
            }
            if perception.surface else None
        ),
        "primitives": [
            {
                "id": p.id,
                "kind": p.kind,
                "source": p.source,
                "geometry": p.geometry.as_dict(),
                "content": p.content,
                "confidence": round(p.confidence, 4),
                "shape": p.shape,
                "source_group": p.source_group,
            }
            for p in perception.primitives
        ],
        "descriptors": {
            pid: {
                "values": {
                    k: (round(v, 3) if isinstance(v, float) else v)
                    for k, v in d.values.items()
                },
                "invalid": sorted(d.invalid),
            }
            for pid, d in sorted(perception.descriptors.items())
        },
        "regions": [
            {
                "id": r.id,
                "geometry": r.geometry.as_dict(),
                "primitive_ids": list(r.primitive_ids),
                "confidence": round(r.confidence, 3),
                "context": dict(r.context),
            }
            for r in perception.regions
        ],
        "groups": [
            {
                "id": g.id,
                "region_id": g.region_id,
                "member_ids": list(g.member_ids),
                "axis": g.axis,
                "pitch": round(g.pitch, 2) if g.pitch else None,
                "rhythm_regularity": round(g.rhythm_regularity, 3),
            }
            for g in perception.groups
        ],
        "classes": [
            {
                "id": c.id,
                "group_id": c.group_id,
                "region_id": c.region_id,
                "member_ids": list(c.member_ids),
                "role": c.role,
                "usable_as_reference": c.usable_as_reference,
                "reason_unusable": c.reason_unusable,
            }
            for c in perception.classes
        ],
        "states": [s.as_dict() for s in perception.states],
        "types": [
            {
                "target_id": t.target_id,
                "structural": t.structural,
                "attributes": dict(t.attributes),
                "semantic_hint": t.semantic_hint,
                "hint_confidence": round(t.hint_confidence, 3),
            }
            for t in perception.types
        ],
        "identity": (
            {
                "screen_id": perception.identity.screen_id,
                "title_text": perception.identity.title_text,
                "content_fingerprint": perception.identity.content_fingerprint,
                "structure_fingerprint": perception.identity.structure_fingerprint,
                "confidence": round(perception.identity.confidence, 3),
            }
            if perception.identity else None
        ),
        "abstentions": [a.as_dict() for a in perception.abstentions],
        "provenance": [r.as_dict() for r in perception.provenance],
    }
