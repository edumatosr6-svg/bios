"""E7 -- State. Who deviates from their class, in which channel, how far.

State is a relation, not a property (§1.1). Every decision here is made
against the element's own class, and never against an absolute colour,
distance or threshold. That is the property that makes the engine
vendor-independent: not the absence of `if vendor ==`, but the absence of
any constant that a new interface could invalidate.

**Channels are evaluated separately and then combined.** Different
interfaces mark the same state by different means -- one inverts the
background, another recolours the text, a third dims everything else.
Collapsing them into a single distance destroys exactly the information
that lets one mechanism cover all three. Which channels agreed is
recorded as evidence, because two independent channels pointing at the
same element is worth more than one channel pointing twice.

**The decision rule is scale-free.** The prototype used a "runner-up"
test for menu strips -- the winner must beat the second place by a ratio
-- while the body used an absolute floor tuned on one population. The
ratio test is the better idea and is promoted here to the general rule
for every channel: it needs no absolute calibration, so it does not have
to be retuned per interface. Deviation itself is expressed in units of
the class's own dispersion, which is the second half of the same idea.

**Leave-one-out.** The element under test is excluded from its own
reference. Without that, a strong highlight drags the median toward
itself and hides -- severe in the small classes that menus always are.
"""
from typing import Any

import numpy as np

from ..model import Abstention, Perception, State
from ..pipeline import StageOutput

MIN_DEVIATION = 3.0             # in units of the class's own dispersion
RUNNER_UP_RATIO = 1.8           # winner must clearly beat second place
MIN_CONFIDENCE = 0.35
EPS = 1e-6

# Below this class size, one channel on its own is not enough.
#
# Every number here is a ratio against the class's own dispersion, and
# leave-one-out estimates that dispersion from the *other* members. At
# the minimum class size of 3 that is a median and a deviation over two
# values -- an estimate with no power, which any photographic noise can
# dominate. Measured on a live Positivo Boot screen: a class of three
# identical "Enabled" dropdown values produced a "selected" at deviation
# 6.16 against a runner-up of 3.15, clearing both thresholds with nothing
# whatsoever to distinguish its members; a class of three dropdowns
# elected the wrong one at 10.04. The genuine selection on the same
# screen sat in a class of six and scored 31.07.
#
# The rule is about the reliability of the statistic, not about any
# interface: when the reference population is that thin, a lone channel
# is asserting more than it measured, and a second independent channel
# has to agree before the engine will say it. Two channels agreeing was
# already the engine's stated standard of better evidence (F4) -- this
# makes it a requirement exactly where the evidence is thinnest.
MIN_SIZE_FOR_SINGLE_CHANNEL = 4

# Dispersion floor, in the units the descriptors are measured in.
#
# Scaling a deviation by the class's own spread is what makes the rule
# free of absolute calibration -- but it degenerates when the population
# is *very* uniform. A menu whose entries are pixel-identical has a
# spread near zero, so an irrelevant difference divides by almost nothing
# and reports an enormous deviation. Measured on the Positivo sidebar:
# the real highlight scored 24.9 on background, while sensor noise on the
# chroma of an unremarkable entry scored 21.9 and pointed at the wrong
# item, which was enough to make the two channels disagree and the whole
# class abstain.
#
# The floor says: differences below the noise of the measurement are not
# evidence, however uniform the neighbours are. It is a property of the
# sensor, not of any interface, so it does not reintroduce per-vendor
# calibration.
NOISE_FLOOR = 1.5

# name -> (descriptor, direction, state it indicates, isolation ratio)
#   direction +1 = only an increase counts, -1 = only a decrease, 0 = either
#   isolation ratio: None = use RUNNER_UP_RATIO, same as every other
#   channel. A channel can instead declare its own, stricter bar -- see
#   S6_border below for why one needs to.
CHANNELS: tuple[tuple[str, str, int, str, float | None], ...] = (
    ("S1_background", "bg_local", 0, "selected", None),
    ("S2_chroma", "ink_chroma", 0, "selected", None),
    ("S3_polarity", "contrast_polarity", 0, "selected", None),
    ("S6_border", "border_strength", 1, "focused", 4.0),
)

# S6, not S4 -- docs/architecture/VISUAL_FEATURE_SPEC.md §7.2 reserves S4
# for stroke weight and S6 for "Moldura" (border_box unique to one
# element -> focused). Follows the doc's numbering rather than
# introducing a new one.
#
# `direction=1`: only a *more* dispersed ring than the class's own
# counts. A flatter-than-peers ring is not evidence of anything -- it
# would just be a different draw of the same sensor noise the class-size
# rule below already exists to survive -- so this is thrown out exactly
# like contrast_polarity's sign check, not a new idea.
#
# State name is `focused`, not `selected`: a keyboard-focused dropdown
# and a highlighted menu entry are different things, and the vocabulary
# already distinguishes them (docs/architecture/VISUAL_FEATURE_SPEC.md
# §7.4). Nothing downstream treats state names as a closed set.
#
# **Why this channel gets its own, higher bar (4.0x, not RUNNER_UP_RATIO
# 1.8x).** S1-S3 read the *interior* of a primitive's own box, which
# E3's occupancy mask already keeps clean of every other detected
# primitive. This channel reads a thin band *outside* the box, on
# purpose -- a real border sits there -- which means it is exposed to
# whatever is nearby that the engine did *not* detect as its own
# primitive: JPEG blur, anti-aliasing halos, a neighbour's descender.
# Measured on live captures, three cases with no real border at all
# still cleared RUNNER_UP_RATIO: a 3-member class of identical "Enabled"
# values scored 1.97x, a line of dense body text wrapped tight against
# its own continuation scored 1.91x, a warning banner packed against the
# item below it scored 2.77x -- the last of those in a class of 9, so
# MIN_SIZE_FOR_SINGLE_CHANNEL did not even apply. The one genuine focus
# ring measured, on a live Boot screen's settings_list, scored 5.38x.
# 4.0 sits in the gap between the worst false positive and the one true
# positive, with margin on both sides.
#
# Clearing 4.0x is also what exempts this channel from the thin-class
# corroboration rule below, in place of a second, separately-tuned
# constant fit to a single data point: S1-S3 need a *population*
# (MIN_SIZE_FOR_SINGLE_CHANNEL) plus a second channel to be trusted
# alone in a small class; this channel substitutes a bar high enough
# that clearing it is itself the corroboration.

# S5 (dimming -> `disabled`) is deliberately NOT in the v1 channel set.
#
# A drop in contrast is ambiguous. An entry greyed out because it is
# unavailable loses contrast -- and so does an entry that just gained a
# highlight bar, because the bar changes the local background and the
# text-to-background difference moves with it. On the Positivo fixtures
# the channel labelled genuinely *selected* entries as `disabled`, which
# is a confidently wrong answer rather than a missing one.
#
# The obvious corroboration -- require the ink to also lose chroma, since
# greying pulls colour toward neutral -- was implemented and measured, and
# does not discriminate: a light highlight bar behind dark text moves the
# ink toward neutral just as effectively. Both readings survive the test,
# so the test decides nothing.
#
# Rather than ship a channel that produces contradictory states, it stays
# out until a signal that genuinely separates the two exists. The
# strongest candidate is temporal (§4): a highlight moves when the
# operator navigates and a disabled entry does not. That needs the
# multi-frame path, which is a v2 concern.
DISABLED_CHANNEL_DEFERRED = "needs a signal that separates dimming from highlighting"

# States that cannot both be true of one element. If two channels ever
# claim contradictory states, the engine reports neither and says why:
# silence is recoverable downstream, a contradiction is not.
CONTRADICTORY: tuple[frozenset[str], ...] = (
    frozenset({"selected", "disabled"}),
)


class StateInference:
    name = "E7.state"
    produces = "state"
    consumes = ("descriptors", "class")

    def run(self, perception: Perception) -> StageOutput:
        if not perception.classes:
            return StageOutput(
                abstentions=(
                    Abstention(stage=self.name, level="state", scope_id=None,
                               reason="no_classes"),
                )
            )

        states: list[State] = []
        abstentions: list[Abstention] = []

        for klass in perception.classes:
            if not klass.usable_as_reference:
                # E6 already recorded why; not repeated here.
                continue

            hits: dict[str, list[tuple[str, float]]] = {}
            self_corroborating: set[tuple[str, str]] = set()
            for channel, descriptor, direction, state_name, isolation_ratio in CHANNELS:
                winner = _evaluate(perception, klass, descriptor, direction, isolation_ratio)
                if winner is None:
                    continue
                element_id, deviation = winner
                hits.setdefault((element_id, state_name), []).append((channel, deviation))
                if isolation_ratio is not None:
                    self_corroborating.add((element_id, state_name))

            hits, contradictions = _drop_contradictions(hits)
            for element_id, names in contradictions:
                abstentions.append(
                    Abstention(
                        stage=self.name, level="state", scope_id=klass.id,
                        reason="contradictory_states_for_one_element",
                        detail={"element": element_id, "states": sorted(names)},
                    )
                )

            # A thin class cannot support a single channel's word for it --
            # unless that channel already cleared its own, stricter
            # isolation bar, which stands in for corroboration (see
            # S6_border's comment on CHANNELS above).
            if klass.size < MIN_SIZE_FOR_SINGLE_CHANNEL:
                uncorroborated = [
                    k for k, evidence in hits.items()
                    if len(evidence) < 2 and k not in self_corroborating
                ]
                for element_id, state_name in uncorroborated:
                    abstentions.append(
                        Abstention(
                            stage=self.name, level="state", scope_id=klass.id,
                            reason="single_channel_on_thin_class",
                            detail={
                                "element": element_id, "state": state_name,
                                "size": klass.size,
                                "minimum": MIN_SIZE_FOR_SINGLE_CHANNEL,
                                "channels": [c for c, _ in hits[(element_id, state_name)]],
                            },
                        )
                    )
                hits = {k: v for k, v in hits.items()
                       if len(v) >= 2 or k in self_corroborating}

            if not hits:
                abstentions.append(
                    Abstention(
                        stage=self.name, level="state", scope_id=klass.id,
                        reason="no_channel_singled_out_a_member",
                        detail={"role": klass.role, "size": klass.size},
                    )
                )
                continue

            # Cardinality prior: one selection per class. Several members
            # claiming it means the class is not showing one, so abstain
            # rather than pick the loudest.
            selected = [k for k in hits if k[1] == "selected"]
            if len(selected) > 1:
                abstentions.append(
                    Abstention(
                        stage=self.name, level="state", scope_id=klass.id,
                        reason="multiple_candidates_for_single_selection",
                        detail={
                            "candidates": [k[0] for k in selected],
                            "role": klass.role,
                        },
                    )
                )
                hits = {k: v for k, v in hits.items() if k[1] != "selected"}

            for (element_id, state_name), evidence in sorted(hits.items()):
                channels = tuple(sorted(c for c, _ in evidence))
                magnitude = max(d for _, d in evidence)
                confidence = _confidence(magnitude, len(channels))
                if confidence < MIN_CONFIDENCE:
                    abstentions.append(
                        Abstention(
                            stage=self.name, level="state", scope_id=klass.id,
                            reason="evidence_below_confidence_floor",
                            detail={"element": element_id, "confidence": round(confidence, 3)},
                        )
                    )
                    continue
                states.append(
                    State(
                        element_id=element_id,
                        class_id=klass.id,
                        name=state_name,
                        channels=channels,
                        magnitude=magnitude,
                        confidence=confidence,
                        evidence={c: round(d, 3) for c, d in evidence},
                    )
                )

        states.sort(key=lambda s: (s.class_id, s.element_id, s.name))
        return StageOutput(
            products=tuple(states),
            abstentions=tuple(abstentions),
            notes=(f"{len(states)} state(s)",),
            parameters={
                "min_deviation": MIN_DEVIATION,
                "runner_up_ratio": RUNNER_UP_RATIO,
                "channels": [c[0] for c in CHANNELS],
                "rule": "leave_one_out + scale_free_runner_up",
            },
        )


def measure(
    perception: Perception, klass, descriptor: str, direction: int
) -> tuple[dict[str, float], dict[str, Any], dict[str, float]]:
    """Deviation of each member from the others, in dispersion units.

    Kept separate from the decision below so that the explain view
    (`perception.explain`) can report what *every* member measured, not
    only the one that won. E7 otherwise discards the losers, which is
    exactly the information needed to tell "this element stood out" from
    "nothing stood out and the winner is noise" -- and an answer the
    engine cannot justify is worth little more than no answer (§F4).

    Both callers go through here so the explanation cannot drift away
    from the decision it claims to explain.
    """
    values: dict[str, Any] = {}
    for member_id in klass.member_ids:
        value = perception.desc(member_id).get(descriptor)
        if value is not None:
            values[member_id] = np.atleast_1d(np.asarray(value, dtype=float))

    if len(values) < 3:
        return {}, values, {}

    deviations: dict[str, float] = {}
    spreads: dict[str, float] = {}
    for member_id, value in values.items():
        others = [v for mid, v in values.items() if mid != member_id]
        stack = np.vstack(others)
        centre = np.median(stack, axis=0)
        raw_spread = float(np.median(np.abs(stack - centre), axis=0).mean())
        spread = max(raw_spread, NOISE_FLOOR)
        distance = float(np.linalg.norm(value - centre))

        if direction != 0:
            signed = float((value - centre).mean())
            if direction > 0 and signed <= 0:
                continue
            if direction < 0 and signed >= 0:
                continue

        deviations[member_id] = distance / spread
        # The *measured* dispersion, before the floor is applied. When
        # this sits under NOISE_FLOOR the class is uniform to within
        # sensor noise, and every deviation computed from it is a ratio
        # against a number the measurement cannot actually resolve.
        spreads[member_id] = raw_spread

    return deviations, values, spreads


def _evaluate(
    perception: Perception, klass, descriptor: str, direction: int,
    isolation_ratio: float | None = None,
) -> tuple[str, float] | None:
    """The winner of a channel, if the class produced one at all.

    `isolation_ratio` overrides RUNNER_UP_RATIO for channels that declare
    their own, stricter bar in CHANNELS -- see S6_border there for why.

    Needing a runner-up at all, not just `deviations` being non-empty, is
    right for a two-sided channel (S1-S3): `measure()` already requires
    3+ members with a value, and nothing there filters any of them out,
    so a runner-up always exists if a winner does. It is wrong for a
    directional one (`direction != 0`): filtering to "only members that
    moved the *right* way" is exactly what leaves a single genuine
    outlier standing alone, which is the strongest case there is, not a
    degenerate one.

    A lone survivor still needs a runner-up to be *scale-free* against,
    though -- without one, `ratio * max(runner_up_dev, EPS)` collapses to
    a number near zero and the whole isolation bar stops discriminating
    anything, which measured false positive on a synthetic fixture's
    footer text at deviation 4.50: comfortably over MIN_DEVIATION alone,
    nowhere near the 4.0x this channel is supposed to require. NOISE_FLOOR
    is what this codebase already uses elsewhere as "the dispersion below
    which nothing is trusted as real" (see its own docstring above), so a
    missing runner-up is treated as sitting exactly there -- not as zero,
    which would mean "infinitely more remarkable than nothing", and not
    as a second real value, which does not exist to compare against.

    **A channel with its own isolation_ratio also requires genuine
    dispersion, not just a floored one.** On a synthetic screenshot --
    pixel-perfect rendering, none of a camera's sensor noise or JPEG
    blur -- a class's *raw* spread (before NOISE_FLOOR clamps it) is
    often exactly 0.0: every member really is pixel-identical apart from
    the one thing being measured. Dividing by the floor at that point
    does not measure deviation from real-world variation, because there
    was none to begin with; it measures the winner's raw distance
    against an arbitrary constant, and any two members that merely
    differ in text length clear it. Measured on synthetic fixtures: a
    footer line scored deviation 59.05 this way, another scored 9.19 --
    both from raw spread of 0.0, neither a real border. The one genuine
    border measured (a live camera photo) had raw spread 3.70, well
    above the floor: real sensor noise is never exactly zero. S1-S3 do
    not need this guard -- they are not the channel that is fragile
    enough to require its own stricter isolation_ratio in the first
    place, and they have a track record of firing correctly on floored
    dispersion (a live "Boot" menu scored 31.07 off a floored 0.67).
    """
    deviations, _, spreads = measure(perception, klass, descriptor, direction)
    if not deviations:
        return None

    ranked = sorted(deviations.items(), key=lambda kv: (-kv[1], kv[0]))
    winner_id, winner_dev = ranked[0]
    runner_up_dev = ranked[1][1] if len(ranked) > 1 else NOISE_FLOOR
    ratio = isolation_ratio if isolation_ratio is not None else RUNNER_UP_RATIO

    if isolation_ratio is not None and spreads.get(winner_id, 0.0) <= EPS:
        return None
    if winner_dev < MIN_DEVIATION:
        return None
    if winner_dev < ratio * max(runner_up_dev, EPS):
        return None
    return winner_id, winner_dev


def _drop_contradictions(hits: dict) -> tuple[dict, list[tuple[str, set[str]]]]:
    """Remove every state of any element that carries contradictory ones.

    Not "pick the stronger": if two channels disagree about what an
    element *is*, the engine has no basis to prefer one, and asserting
    either would be a guess dressed as a measurement.
    """
    by_element: dict[str, set[str]] = {}
    for element_id, state_name in hits:
        by_element.setdefault(element_id, set()).add(state_name)

    contradictions = [
        (element_id, names)
        for element_id, names in by_element.items()
        if any(len(names & pair) > 1 for pair in CONTRADICTORY)
    ]
    blocked = {element_id for element_id, _ in contradictions}
    kept = {k: v for k, v in hits.items() if k[0] not in blocked}
    return kept, sorted(contradictions)


def _confidence(magnitude: float, n_channels: int) -> float:
    """Saturating in magnitude, rewarded for independent agreement.

    Deliberately not a probability -- it is an ordering the cognition
    layer can threshold, and calling it a probability would imply a
    calibration the engine has not earned yet (§11.2).
    """
    base = magnitude / (magnitude + MIN_DEVIATION)
    agreement = 1.0 - 0.5 ** n_channels
    return float(min(0.99, base * (0.7 + 0.3 * agreement / 0.5)))
