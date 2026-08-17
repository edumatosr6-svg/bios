"""Why the engine concluded what it concluded -- the decision, opened up.

The engine is built to abstain rather than guess, and it records *that*
it abstained. What it does not record is the arithmetic behind either
outcome: E7 keeps the winner of each channel and discards every other
member's measurement, so a report of "selected: X" and a report of
"nothing stood out" look equally authoritative from the outside even
when one of them is noise that happened to clear a threshold.

This view reconstructs the chain -- region, group, class, and then every
channel's per-member measurement -- so a wrong answer can be read back to
the stage that produced it. It changes nothing: it re-runs E7's own
`measure()` over the same perception, which is why the numbers here are
the numbers the decision used.

Reading it: a class whose winner beats the runner-up by a wide margin is
a real signal. A class where every member sits at a similar deviation and
the winner scrapes past the threshold is the engine finding *something*
in the absence of the marker the interface actually uses -- the
signature of a missing channel, not of a present state.
"""
from typing import Any

from .stages.e7_state import (
    CHANNELS,
    EPS,
    MIN_DEVIATION,
    NOISE_FLOOR,
    RUNNER_UP_RATIO,
    measure,
)


def explain(perception: Any) -> str:
    lines: list[str] = []
    by_id = perception.primitives_by_id()

    def label(pid: str, width: int = 26) -> str:
        primitive = by_id.get(pid)
        text = (primitive.content if primitive and primitive.content else pid) or pid
        return text[:width]

    lines.append("=" * 78)
    lines.append("WHY THE ENGINE DECIDED THIS")
    lines.append("=" * 78)

    surface = perception.surface
    if surface is not None:
        lines.append(f"surface  {surface.width}x{surface.height} "
                     f"rectified={surface.rectified}")

    lines.append("")
    lines.append(f"REGIONS ({len(perception.regions)}) -- where comparing is legitimate")
    for region in perception.regions:
        g = region.geometry
        symbolic = sum(1 for pid in region.primitive_ids
                       if (p := by_id.get(pid)) and p.is_symbolic and p.content)
        lines.append(f"  {region.id}  x={g.x:<5} y={g.y:<5} {g.w}x{g.h:<5} "
                     f"{len(region.primitive_ids):>3} primitives ({symbolic} with text)")

    lines.append("")
    lines.append(f"GROUPS ({len(perception.groups)}) -- what forms a perceptual unit")
    for group in perception.groups:
        pitch = f"{group.pitch:.1f}" if group.pitch else "-"
        lines.append(f"  {group.id}  axis={group.axis:<10} pitch={pitch:>7} "
                     f"regularity={group.rhythm_regularity:.2f}  "
                     f"{len(group.member_ids)} members")
        lines.append(f"      {[label(m, 18) for m in group.member_ids]}")

    lines.append("")
    lines.append(f"CLASSES ({len(perception.classes)}) -- who is comparable with whom")
    for klass in perception.classes:
        mark = "" if klass.usable_as_reference else f"  UNUSABLE ({klass.reason_unusable})"
        lines.append(f"  {klass.id}  role={klass.role:<22} size={klass.size}{mark}")
        lines.append(f"      {[label(m, 18) for m in klass.member_ids]}")

    lines.append("")
    lines.append("CHANNEL MEASUREMENTS -- the arithmetic behind every verdict")
    lines.append(f"  thresholds: deviation >= {MIN_DEVIATION}, "
                 f"winner >= {RUNNER_UP_RATIO}x runner-up, "
                 f"dispersion floor {NOISE_FLOOR}")

    for klass in perception.classes:
        if not klass.usable_as_reference:
            continue
        lines.append("")
        lines.append(f"  {klass.id} ({klass.role}, {klass.size} members)")
        for channel, descriptor, direction, state_name, isolation_ratio in CHANNELS:
            deviations, values, spreads = measure(perception, klass, descriptor, direction)
            if not deviations:
                missing = klass.size - len(values)
                why = (f"only {len(values)} of {klass.size} members have "
                       f"{descriptor!r}" if missing else "no comparable values")
                lines.append(f"    {channel:<16} -- not evaluated ({why})")
                continue

            required_ratio = isolation_ratio if isolation_ratio is not None else RUNNER_UP_RATIO
            ranked = sorted(deviations.items(), key=lambda kv: (-kv[1], kv[0]))
            best_id, best = ranked[0]
            # Mirrors _evaluate()'s own fallback exactly -- see its
            # docstring for why a missing runner-up is NOISE_FLOOR, not 0.
            runner_up = ranked[1][1] if len(ranked) > 1 else NOISE_FLOOR
            ratio = best / max(runner_up, EPS)

            # Mirrors _evaluate()'s own guard -- see its docstring for why
            # an isolation_ratio channel also needs genuine (non-floored)
            # raw dispersion, not just a winner that clears the ratio.
            genuinely_dispersed = (
                isolation_ratio is None or spreads.get(best_id, 0.0) > EPS
            )
            passed_floor = best >= MIN_DEVIATION
            passed_ratio = best >= required_ratio * max(runner_up, EPS)
            if not genuinely_dispersed:
                verdict = ("-> nothing (raw dispersion is exactly 0 -- synthetic "
                           "image, no real variation to measure a deviation from)")
            elif passed_floor and passed_ratio:
                verdict = f"-> {state_name.upper()}: {label(best_id)!r}"
            elif not passed_floor:
                verdict = f"-> nothing (top deviation {best:.2f} < {MIN_DEVIATION})"
            else:
                verdict = (f"-> nothing (winner only {ratio:.2f}x the runner-up, "
                           f"needs {required_ratio}x)")

            typical = min(spreads.values()) if spreads else 0.0
            floored = (" (FLOORED -- class uniform to within sensor noise)"
                       if typical < NOISE_FLOOR else "")
            lines.append(f"    {channel:<16} {verdict}")
            lines.append(f"        measured dispersion {typical:.2f}{floored}")
            for member_id, deviation in ranked:
                flag = "  <- winner" if member_id == best_id else ""
                if len(ranked) > 1 and member_id == ranked[1][0]:
                    flag = "  <- runner-up"
                lines.append(f"        {label(member_id, 30):<32} deviation={deviation:6.2f}{flag}")
            skipped = [m for m in klass.member_ids if m not in deviations]
            if skipped:
                lines.append(f"        (not measurable on this channel: "
                             f"{[label(m, 16) for m in skipped]})")

    lines.append("")
    lines.append(f"CONCLUSION ({len(perception.states)} state(s))")
    for state in perception.states:
        evidence = ", ".join(f"{k}={v}" for k, v in sorted(state.evidence.items()))
        lines.append(f"  {state.name}: {label(state.element_id)!r} "
                     f"conf={state.confidence:.2f} in {state.class_id}")
        lines.append(f"      channels that agreed: {', '.join(state.channels)}  [{evidence}]")
    if not perception.states:
        lines.append("  none -- the engine did not single anyone out")

    if perception.abstentions:
        lines.append("")
        lines.append("DID NOT DECIDE")
        counted: dict[str, int] = {}
        for a in perception.abstentions:
            key = f"{a.stage} {a.reason}"
            counted[key] = counted.get(key, 0) + 1
        for key in sorted(counted):
            lines.append(f"  {counted[key]:>3}x {key}")

    return "\n".join(lines)
