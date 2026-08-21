"""Moving the BIOS cursor to a named entry, verifying every step.

The rule the prototype proved and this keeps: **never assume a keypress
landed.** The cable confirms delivery (it ACKs every byte), but delivery
is not the same as the BIOS having moved the highlight -- the screen is
the only authority on where the cursor is, so it is re-read after each
press.

Stop conditions, in priority order:

1. the target is under the cursor -> arrived;
2. the cursor returns to an entry already visited -> the list wrapped (or
   the cursor is stuck at an end) without the target appearing, so it is
   not reachable this way -> stop;
3. `max_steps` exhausted -> stop.

(2) is the one that matters on real hardware. The prototype had only a
blind step cap (`bios_navigate_demo.py:78`), which on a wrapping menu
means pressing a key into a live machine dozens of times before giving
up. Cycle detection notices after exactly one lap.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from . import labels
from .screen import (
    find_group, group_views, legacy_cursor, match_score, normalize,
)

ARRIVED = "arrived"
CYCLED = "not_found_after_full_cycle"
EXHAUSTED = "max_steps_exhausted"
BLIND = "cursor_undetermined"


@dataclass
class NavigationResult:
    ok: bool
    reason: str
    steps: int
    cursor: str | None = None
    visited: list = field(default_factory=list)
    detail: str | None = None
    reading: object = None


def cursor_group(full, hint=None, target=None):
    """The group the keyboard is currently in.

    Preference order matters. A group that actually holds a `focused`
    element is direct evidence of where the cursor is, so it wins over
    both the semantic hint (the engine's guess, measured at only 0.35-0.67
    confidence) and over looking for the target -- which may not be on
    screen yet.
    """
    views = group_views(full)
    if hint:
        views = [v for v in views if v.hint == hint]

    with_cursor = [v for v in views if v.cursor is not None]
    if with_cursor:
        return with_cursor[0]
    if target:
        containing = find_group(full, hint=hint, containing=target)
        if containing is not None:
            return containing
    return views[0] if views else None


def move_to(session, target, hint=None, key="down", max_steps=20,
            blind_retries=2, on_step=None, focus_key=None):
    """Press `key` until `target` is the entry under the cursor.

    `blind_retries` re-reads (without pressing) when the engine cannot
    determine the cursor. The engine is documented to give different
    answers on different captures of the same screen
    (docs/specs/p-specs/campo-focado-por-borda-sem-canal-no-e7.md), so a
    single abstention is worth re-reading; it is never worth pressing a
    key blindly, which would lose track of where the cursor is.

    `focus_key`, pressed once before the walk starts, hands keyboard
    focus to the region `target` actually lives in. Confirmed necessary
    live (2026-08-21, Positivo BIOS): with focus left in the content
    panel, `key="down"` scrolls that panel's own fields and never touches
    the sidebar at all -- eight presses walked through CPU cache figures
    without the sidebar's active tab changing once. That looks exactly
    like a stuck cursor detector from the outside (the same highlighted
    line keeps being reported) but the real cause is that focus was never
    where the walk assumed it was.
    """
    if focus_key:
        session.press(focus_key)
    reading = session.read_cursor()
    visited = []
    blind = 0

    for step in range(max_steps + 1):
        marked = legacy_cursor(reading, prefer_target=target)

        if marked is None:
            if blind < blind_retries:
                blind += 1
                reading = session.read_cursor()
                continue
            return NavigationResult(
                ok=False, reason=BLIND, steps=step, visited=visited,
                detail="nothing on screen is marked as the cursor",
                reading=reading,
            )
        blind = 0

        if match_score(target, marked["text"]):
            return NavigationResult(
                ok=True, reason=ARRIVED, steps=step, cursor=marked["text"],
                visited=visited, reading=reading,
            )

        seen = normalize(marked["text"])
        if seen in visited:
            return NavigationResult(
                ok=False, reason=CYCLED, steps=step, cursor=marked["text"],
                visited=visited,
                detail=f"{target!r} never came under the cursor",
                reading=reading,
            )
        visited.append(seen)

        if step == max_steps:
            break
        if on_step:
            on_step(step + 1, marked["text"])
        session.press(key)
        reading = session.read_cursor()

    return NavigationResult(
        ok=False, reason=EXHAUSTED, steps=max_steps, visited=visited,
        detail=f"gave up after {max_steps} presses of {key!r}",
        reading=reading,
    )


def activate(session, key="enter"):
    """Open whatever the cursor is on, and return the screen it landed on."""
    session.press(key)
    return session.read_stable()


# How far right of the screen edge the sidebar column extends. Measured on
# the live Positivo capture: sidebar entries sit at x=120, the "Setup"
# label/icon up to x~250; content starts at x~428. 300 clears both with
# margin without reaching into content.
SIDEBAR_MAX_X = 300


def _sidebar_colour_fallback(reading, target):
    """Last resort when selection.py's own detector abstains entirely on
    the sidebar (`legacy_cursor` finds nothing marked at all).

    Confirmed live 2026-08-21 (Positivo BIOS): the sidebar's un-marked
    entries render white text on a shared light-grey background; the
    *currently displayed page* and the *keyboard cursor position* both
    render darker text instead of the background colour changing -- and
    when those two differ (cursor sits on an entry that isn't the
    displayed page), that is TWO simultaneously odd-coloured lines.
    selection.py's own MAX_TEXT_COLOR_OUTLIERS=1 cap then abstains by
    design: a BIOS shows exactly one selection, so more than one
    odd-coloured line normally means "no selection is being shown", not
    "which one do I pick". That reasoning is right when the cap is
    guarding against an ambiguous *single* signal -- it is wrong here,
    where the two colours carry two *different*, already-understood
    meanings, and this function already knows which specific entry it is
    looking for. So it checks only `target`'s own text colour against the
    sidebar's own white baseline -- it never picks among unrelated
    candidates the way selection.py's population statistics do, which is
    what keeps this from re-opening the false-positive risk the cap
    exists to prevent.
    """
    lines = [line for block in reading.get("blocks", ())
             for line in block.get("lines", ())]
    sidebar = [line for line in lines if line["bbox"]["left"] < SIDEBAR_MAX_X]
    colours = [tuple(line["fg_color"]) for line in sidebar if line.get("fg_color")]
    if len(colours) < 3:
        return None  # too few entries read to trust a baseline

    baseline = Counter(colours).most_common(1)[0][0]
    for line in sidebar:
        if not match_score(target, line["text"]):
            continue
        fg = line.get("fg_color")
        if fg and tuple(fg) != baseline:
            return line
    return None


def enter_main_menu_screen(session, screen, activate_key=None, max_steps=20):
    """Get to a top-level sidebar screen (Main/Advanced/Security/...), from
    wherever the BIOS currently is, and open it.

    The one building block every tool needing a specific top-level page
    should call, instead of hand-declaring a `nav_menu` Step -- centralised
    after `cpu_temperature`'s route shipped with the sidebar leg missing
    `focus_key="left"` (arrow keys are scoped to whichever region has
    keyboard focus, default content, see `move_to`'s docstring) and, once
    fixed, its sibling tools (`bios_info`/`main_info`) turned out to hit a
    second, different failure the same day -- the colour-ambiguity case
    `_sidebar_colour_fallback` exists for. One shared function means a fix
    to either problem reaches every tool that navigates the sidebar,
    instead of needing to be copied into each tool's own route.

    `screen` is a canonical name from `labels.SCREENS`. Moving the cursor
    to a sidebar entry already switches the displayed page on this BIOS,
    so `activate_key` defaults to None (nothing to press); pass "enter"
    for a BIOS where the sidebar needs an explicit open.
    """
    target = labels.screen(screen)
    outcome = move_to(session, target, hint="nav_menu", key="down",
                      focus_key="left", max_steps=max_steps)

    if not outcome.ok and outcome.reason == BLIND:
        marked = _sidebar_colour_fallback(outcome.reading, target)
        if marked is not None:
            outcome = NavigationResult(
                ok=True, reason=ARRIVED, steps=outcome.steps,
                cursor=marked["text"], visited=outcome.visited,
                reading=outcome.reading,
            )

    if outcome.ok and activate_key:
        return outcome, activate(session, activate_key)
    # `outcome.reading` is the legacy cursor dict move_to reads with, not
    # a perception Reading -- callers that go on to read a field/value
    # need the contract (`.full`), so re-read through the normal path
    # once navigation is confirmed, same as every other leg does.
    return outcome, (session.read_stable() if outcome.ok else outcome.reading)


OPPOSITE = {"down": "up", "up": "down", "right": "left", "left": "right"}


def axis_key(full, group_id, default="down"):
    """The arrow that moves along a group's own axis.

    A vertical sidebar walks with down/up, a horizontal tab strip with
    right/left. The engine already reports the axis it measured
    (`groups[].axis`), so this does not have to be declared per BIOS model.
    """
    for group in full.get("groups", ()):
        if group["id"] == group_id:
            return "right" if group.get("axis") == "horizontal" else "down"
    return default


@dataclass
class WalkResult:
    entries: list = field(default_factory=list)
    steps: int = 0
    complete: bool = False
    moved: bool = False
    detail: str | None = None
    reading: object = None


# How a directional pass ended. The first two are successes; they differ
# because only a stall leaves ground uncovered behind the starting point.
CYCLE = "cycle"    # came back round to where this pass started
STALL = "stall"    # cursor stopped moving: an end of a non-wrapping list


def _walk_one_way(session, hint, key, max_steps, seen, order):
    """Press `key` until this direction has nothing left to show.

    Stops on returning to **this pass's own starting entry** (a full lap)
    or on the cursor not moving (an end). Deliberately does not stop at
    just any already-seen entry: the reverse pass starts on ground the
    forward pass already covered, and bailing there would end it before
    it moved at all.
    """
    steps = 0
    reading = session.read_cursor()
    start = previous = None

    for _ in range(max_steps):
        marked = legacy_cursor(reading)
        if marked is None:
            return steps, reading, "cursor_undetermined"

        token = normalize(marked["text"])
        if start is None:
            start = token
        elif token == start:
            return steps, reading, CYCLE
        if token == previous:
            return steps, reading, STALL
        if token not in seen:
            seen.add(token)
            order.append(marked["text"])
        previous = token

        session.press(key)
        steps += 1
        reading = session.read_cursor()
    return steps, reading, "max_steps_exhausted"


def walk_group(session, hint="nav_menu", key=None, max_steps=20, focus_key=None):
    """Step the cursor through every entry of a menu and report them.

    Why walk at all, when one reading already lists the group's text: the
    reading also picks up text that merely shares the column. Measured on
    `captures/positivo_advanced_hardware-monitor.jpg`, the `nav_menu`
    group contains 'POSITIVO' and 'Setup' -- the logo -- alongside the six
    real entries. The cursor never lands on those, so walking is what
    separates a selectable option from decoration.

    Both directions are walked. A BIOS menu that wraps is fully covered by
    one pass, but one that stops at its ends is not -- starting halfway
    down such a menu, a single downward pass would silently report only
    the bottom half.
    """
    if focus_key:
        session.press(focus_key)

    probe = session.read_stable()
    group = cursor_group(probe.full, hint=hint)
    key = key or (axis_key(probe.full, group.group_id) if group else "down")

    seen, order = set(), []
    steps, reading, outcome = _walk_one_way(session, hint, key, max_steps,
                                            seen, order)

    # Only a stall leaves ground uncovered: the cursor hit an end, so
    # whatever sits above the starting point was never visited. A full lap
    # already covered everything, and walking back would just re-tread it.
    back = OPPOSITE.get(key)
    if outcome == STALL and back:
        forward = list(order)
        extra, reading, outcome = _walk_one_way(
            session, hint, back, max_steps, seen, order
        )
        steps += extra
        # Entries found going backwards sit above the starting point, and
        # were collected in reverse -- flip them back so the reported
        # order matches the order on screen.
        order = list(reversed(order[len(forward):])) + forward

    complete = outcome in (CYCLE, STALL)
    return WalkResult(
        entries=order, steps=steps, complete=complete,
        # One entry means the cursor never actually went anywhere: the
        # walk confirmed nothing, whatever the single reading showed.
        moved=len(order) > 1,
        detail=None if complete else outcome,
        reading=reading,
    )
