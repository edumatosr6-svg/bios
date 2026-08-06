"""E8 -- Typing. Name structure without inventing meaning.

Two fields, strictly separated (§E8). `structural` is decidable from the
surface: a run of similar things evenly spaced along an axis is a
Repeater whatever it turns out to mean. `semantic_hint` is an opinion
with a confidence, and the cognition layer may throw it away without
losing the fact underneath.

The separation is not pedantry. "Vertical menu", "list" and "tab bar" are
visually identical -- N similar elements, aligned, regular pitch, one of
them different. What distinguishes them is behaviour: whether activating
one swaps a panel. Perception cannot see behaviour, so asserting "tab
bar" here would be cognition smuggled into the perception layer, which is
the one thing the architecture exists to prevent.
"""
from ..model import Perception, StructuralType
from ..pipeline import StageOutput

EDGE_MARGIN = 0.22              # fraction of surface size counted as "at the edge"
STRONG_RHYTHM = 0.7


class Typing:
    name = "E8.typing"
    produces = "type"
    consumes = ("primitive", "region", "group", "class", "state")

    def run(self, perception: Perception) -> StageOutput:
        surface = perception.surface
        if surface is None or not perception.groups:
            return StageOutput(products=())

        by_id = perception.primitives_by_id()
        types: list[StructuralType] = []

        for group in perception.groups:
            members = [by_id[m] for m in group.member_ids if m in by_id]
            if not members:
                continue

            attributes = {
                "axis": group.axis,
                "cardinality": group.cardinality,
                "rhythm_regularity": round(group.rhythm_regularity, 3),
                "pitch": round(group.pitch, 1) if group.pitch else None,
            }
            structural = (
                "Repeater" if group.rhythm_regularity >= STRONG_RHYTHM
                else "LooseRun"
            )

            hint, confidence = _hint(group, members, surface)
            types.append(
                StructuralType(
                    target_id=group.id,
                    structural=structural,
                    attributes=attributes,
                    semantic_hint=hint,
                    hint_confidence=confidence,
                )
            )

        for region in perception.regions:
            groups_here = [g for g in perception.groups if g.region_id == region.id]
            if len(groups_here) >= 2 and _looks_tabular(groups_here):
                types.append(
                    StructuralType(
                        target_id=region.id,
                        structural="KeyValueTable",
                        attributes={"columns": len(groups_here)},
                        semantic_hint="settings_list",
                        hint_confidence=0.6,
                    )
                )
            else:
                types.append(
                    StructuralType(
                        target_id=region.id,
                        structural="Region",
                        attributes={"groups": len(groups_here)},
                    )
                )

        types.sort(key=lambda t: t.target_id)
        return StageOutput(
            products=tuple(types),
            notes=(f"{len(types)} typed",),
            parameters={"strong_rhythm": STRONG_RHYTHM},
        )


def _hint(group, members, surface) -> tuple[str | None, float]:
    """A guess, and honest about being one.

    Position is weak evidence -- a vertical run hugging the left edge is
    *often* navigation -- so the confidence stays well below certainty no
    matter how clean the geometry is.
    """
    left = min(m.geometry.x for m in members)
    top = min(m.geometry.y for m in members)

    if group.axis == "vertical" and left < EDGE_MARGIN * surface.width:
        return "nav_menu", 0.55 * group.rhythm_regularity + 0.15
    if group.axis == "horizontal" and top < EDGE_MARGIN * surface.height:
        return "tab_bar", 0.5 * group.rhythm_regularity + 0.15
    if group.axis == "vertical":
        return "settings_list", 0.4 * group.rhythm_regularity + 0.1
    return None, 0.0


def _looks_tabular(groups) -> bool:
    """Two or more vertical runs side by side: labels and values."""
    verticals = [g for g in groups if g.axis == "vertical"]
    return len(verticals) >= 2
