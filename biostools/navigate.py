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
            blind_retries=2, on_step=None, focus_key=None, ignore_texts=()):
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

    # Walking anything other than the sidebar: the sidebar's own mark (the
    # displayed page) is always on screen and is never the cursor being
    # walked, so it must not be mistaken for it. Measured 2026-08-24 while
    # walking Advanced's list: on one step the content's highlight bar went
    # undetected and `legacy_cursor` fell back to reporting 'Advanced' --
    # the sidebar page. Two of those in a row look like the cursor sitting
    # still, and the cycle guard ends the walk one entry short of the
    # target.
    if hint and hint != "nav_menu" and not ignore_texts:
        ignore_texts = [text for _, text in sidebar_entries(reading)]

    for step in range(max_steps + 1):
        marked = legacy_cursor(reading, prefer_target=target,
                               ignore_texts=ignore_texts)

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

# The same limit as a fraction of frame width. SIDEBAR_MAX_X above was
# measured on the live 1280x720 HDMI feed, and using it as an absolute
# pixel count silently breaks on any other capture size -- on the 3840-wide
# photographs in `captures/` the whole sidebar sits far to the right of
# 300px, so every sidebar query came back empty. Scaling keeps one
# calibration valid for both input kinds.
SIDEBAR_MAX_X_RATIO = SIDEBAR_MAX_X / 1280


def sidebar_limit(reading):
    """The x below which a line belongs to the sidebar, for this reading.

    Width is taken from the frame when there is one, else from the
    rightmost text on screen, so this works on a reading that carries no
    image (a fixture-driven test) as well as on a live capture.
    """
    frame = reading.get("frame")
    if frame is not None and getattr(frame, "size", 0):
        width = frame.shape[1]
    else:
        width = max((line["bbox"]["left"] + line["bbox"]["width"]
                     for block in reading.get("blocks", ())
                     for line in block.get("lines", ())), default=0)
    return width * SIDEBAR_MAX_X_RATIO if width else SIDEBAR_MAX_X


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
    sidebar = [line for line in lines
               if line["bbox"]["left"] < sidebar_limit(reading)]
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


# Where the circular "back" icon beside the sidebar's "Setup" label sits,
# as fractions of the frame so a different capture resolution still lands
# on it. Measured on the live 1280x720 HDMI feed: x 18..56, y 78..115.
_SETUP_ICON_BOX = (18 / 1280, 78 / 720, 56 / 1280, 115 / 720)

# Fraction of that box's pixels that are near-white. The icon is drawn as
# an OUTLINE ring when the cursor is elsewhere and as a FILLED disc when
# the cursor is on it, so the filled state simply has more white. Measured
# 2026-08-24 across twelve real frames: 0.2496 with the cursor elsewhere
# -- bit-identical across eight different screens, i.e. pure rendering,
# not noise -- against 0.4260 with the cursor parked on it. The midpoint
# is nowhere near either value.
_ICON_FILLED_MIN = 0.33
# Above this the whole box is white, which does not happen for either
# icon state: it means something is covering the sidebar (a modal dialog
# dims the page behind it). Measured 1.0 on exactly the dialog frames.
_ICON_OBSCURED_MIN = 0.90


def setup_icon_focused(frame):
    """True when the sidebar's top "Setup" back-arrow holds the cursor.

    The anchor that makes counted sidebar navigation safe rather than
    hopeful. **The signal is not in any text**, which is why every
    OCR-driven attempt at this missed it: `selection.py` only samples
    colours inside OCR bounding boxes, and this is an icon. Measured
    directly, the word "Setup" renders bit-identically whether or not the
    cursor is on it -- fg [255,255,255], bg [253,220,178], both states --
    while the icon beside it switches between a ring and a filled disc.

    Returns None when the reading cannot be trusted (no frame, or the
    sidebar is covered by a dialog) so a caller can tell "not anchored"
    apart from "could not tell", which are different answers here: the
    first justifies pressing more keys, the second does not.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    height, width = frame.shape[:2]
    fx0, fy0, fx1, fy1 = _SETUP_ICON_BOX
    box = frame[int(fy0 * height):int(fy1 * height),
                int(fx0 * width):int(fx1 * width)]
    if box.size == 0:
        return None

    white = float((box.min(axis=2) > 235).mean())
    if white >= _ICON_OBSCURED_MIN:
        return None
    return white >= _ICON_FILLED_MIN


# Canonical screens that are top-level sidebar entries, so a reading can
# be filtered down to just the menu. Order is NOT taken from here -- it is
# read off the screen -- because a BIOS model may list them differently.
#
# Public under both names on purpose: everything in this module already
# said `_SIDEBAR_SCREENS`, and renaming it would touch every call site for
# no benefit. `TOP_LEVEL_SCREENS` is the name a caller OUTSIDE this module
# should use -- `goto_screen` needs exactly this set (the screens
# `enter_main_menu_screen` can actually reach) to know which names are
# valid to offer the model, as opposed to `labels.SCREENS`, which also
# lists screens like `hardware_monitor` that live inside Advanced and are
# not a sidebar entry `enter_main_menu_screen` can walk to directly.
_SIDEBAR_SCREENS = ("main", "advanced", "security", "boot",
                    "save_and_exit", "event_log")
TOP_LEVEL_SCREENS = _SIDEBAR_SCREENS


def sidebar_entries(reading):
    """The sidebar's menu entries, top to bottom, as drawn.

    Filtered to entries this project has declared spellings for, which
    drops the 'POSITIVO'/'Setup' logo sitting in the same column without
    hardcoding those two strings: anything that is not a menu entry we
    know how to navigate to is not something we can count our way to
    either.
    """
    lines = [line for block in reading.get("blocks", ())
             for line in block.get("lines", ())
             if line["bbox"]["left"] < sidebar_limit(reading)]
    lines.sort(key=lambda l: l["bbox"]["top"])

    entries = []
    for line in lines:
        for canonical in _SIDEBAR_SCREENS:
            if match_score(labels.screen(canonical), line["text"]):
                entries.append((canonical, line["text"]))
                break
    return entries


def resolves_to_screen(text, screen):
    """True when `text` is most plausibly this screen's entry, allowing for
    OCR damage.

    `match_score` is deliberately strict -- it absorbs how a screen is
    *drawn* but not how it is *worded*, because a loose match on a field
    label can silently report the wrong reading (see labels.py). That is
    right for field labels and wrong for *verifying arrival*, where the
    candidates are a known, closed set of six sidebar entries and the only
    question is which one this is.

    Measured live 2026-08-26: a click on 'Advanced' worked -- the page
    really did switch -- but verification rejected it because OCR returned
    **'Avanced'**, one character short. Strict matching turned a correct
    navigation into a reported failure, five times out of six. Picking the
    nearest known entry cannot invent a screen that is not in the list, so
    it does not reopen the silent-wrong-answer risk strictness protects
    against here.

    0.8 was the first cutoff tried and it undershot on the SHORT entries:
    'main' and 'boot' are only 4 characters, so a single swapped/dropped
    character in the middle ('maln', 'mair', '6oot', 'booi', ...) already
    scores 0.75 -- below 0.8 -- while the same class of damage on the
    8-character 'advanced' still scores 0.93. Reported live 2026-08-28: a
    click that visibly landed on 'Main' was reported as a failed
    navigation for exactly this reason. Lowered to 0.7, which still clears
    every cross-screen pair with a wide margin -- the closest two distinct
    screens ('security' and 'save & exit') score only 0.42 against each
    other -- so this still cannot pick the wrong screen from the list, it
    just also accepts the single-character damage a short name is more
    exposed to.
    """
    from difflib import SequenceMatcher

    seen = normalize(text)
    if not seen:
        return False

    best_screen, best_ratio = None, 0.0
    for canonical in _SIDEBAR_SCREENS:
        for spelling in labels.screen(canonical):
            ratio = SequenceMatcher(None, seen, normalize(spelling)).ratio()
            if ratio > best_ratio:
                best_screen, best_ratio = canonical, ratio
    return best_screen == screen and best_ratio >= 0.7


def sidebar_active(reading):
    """The marked entry **inside the sidebar**, or None.

    Not `legacy_cursor`, which searches the whole screen and therefore
    answers with the content panel's own cursor whenever both are marked
    -- the usual case right after opening a page. Verifying arrival needs
    the sidebar's mark specifically, so it has to be selected by geometry
    before any of that tie-breaking runs.
    """
    limit = sidebar_limit(reading)
    marked = [line for block in reading.get("blocks", ())
              for line in block.get("lines", ())
              if line["bbox"]["left"] < limit and line.get("highlighted")]
    return marked[0] if len(marked) == 1 else None


def enter_main_menu_screen_by_click(session, screen, settle_delay=0.0):
    """Reach a top-level page by CLICKING its sidebar entry.

    The portable path. It knows only two things: what the entry is
    called, and that clicking it works -- no wrap behaviour, no back
    arrow, no press counts. Measured live 2026-08-24: one click on a
    sidebar entry both moves *and* opens, where the keyboard needs
    anchor + count + ENTER.

    `settle_delay`: seconds paused right before the click is sent, after
    the pointer has already confirmed its position. Exists to test a
    specific live observation (2026-08-27): repeated clicks through this
    same path failed in CONSECUTIVE runs (e.g. four in a row), not spread
    randomly, which does not look like per-click noise -- it looks like a
    state that gets entered and stays bad for a while. One candidate is a
    window right after a page redraw where the BIOS has not yet resumed
    listening for pointer input; `wait_stable()` only confirms the IMAGE
    stopped changing, which is not the same thing. Defaults to 0.0 (no
    behaviour change) until that hypothesis is actually confirmed live.

    Returns a `NavigationResult` like its keyboard sibling. On any
    pointer trouble it reports failure rather than raising, so the caller
    can fall back -- a BIOS that ignores the mouse is a normal condition
    here (the first Positivo unit does exactly that), not a fault.
    """
    import time

    from .pointer import Pointer, PointerUnavailable

    target = labels.screen(screen)
    reading = session.read_cursor()
    entry = None
    limit = sidebar_limit(reading)
    for block in reading.get("blocks", ()):
        for line in block.get("lines", ()):
            if line["bbox"]["left"] < limit and match_score(target, line["text"]):
                entry = line
                break
    if entry is None:
        return NavigationResult(
            ok=False, reason=CYCLED, steps=0,
            detail=f"{screen!r} nao esta visivel na barra lateral")

    # One calibrated pointer per session, not per call. Calibrating on
    # every call was both the slowest part of this path (~8s) and its
    # biggest reliability drag: measured over six consecutive clicks, two
    # failed outright with "nao localizei o ponteiro" -- failures that only
    # existed because a fresh calibration was attempted each time. The
    # pointer tracks its own position across moves, so one calibration is
    # all the session ever needs; a later failure re-arms it by clearing
    # the cache rather than limping on a stale estimate.
    pointer = getattr(session, "_pointer", None)
    if pointer is None:
        try:
            pointer = Pointer(session)
            pointer.calibrate()
        except PointerUnavailable as exc:
            return NavigationResult(ok=False, reason=BLIND, steps=0,
                                    detail=f"ponteiro indisponivel: {exc}")
        session._pointer = pointer

    bbox = entry["bbox"]
    # In the BLANK part of the row, not on the text. Measured directly
    # 2026-08-26 (pixel-sampled a saved frame): an active sidebar row
    # paints its highlight across the WHOLE sidebar column, x~0 to ~400 at
    # 1280 width, while the label itself only occupies a narrow band in
    # the middle (e.g. 'Boot' spans x=120..190). Aiming inside the text's
    # own bbox means the target sits right next to the OCR box's edge,
    # which jitters a little between reads -- clicking the wide blank
    # margin between the text and the sidebar's own boundary is the same
    # row with far more room for that jitter to land safely. This is the
    # user's own observation, watching the real screen -- there visibly is
    # a gap between where the label ends and the row's selectable edge.
    text_right = bbox["left"] + bbox["width"]
    sidebar_right = sidebar_limit(reading)
    x = (text_right + sidebar_right) / 2 if sidebar_right > text_right else text_right + 20
    y = bbox["top"] + bbox["height"] / 2
    if not pointer.move_to(x, y):
        # Its position estimate is no longer trustworthy; drop it so the
        # next attempt recalibrates instead of compounding the error.
        session._pointer = None
        return NavigationResult(
            ok=False, reason=BLIND, steps=0,
            detail="ponteiro nao convergiu no alvo -- nao cliquei")

    if settle_delay:
        time.sleep(settle_delay)
    session.mouse_click("left")
    after = session.read_cursor()
    if looks_like_dialog(after):
        session.press("esc")
        return NavigationResult(
            ok=False, reason=BLIND, steps=1,
            detail="o clique abriu um dialogo de confirmacao; fechei e parei")

    # Same arrival check the counted path uses: after opening, the sidebar
    # carries exactly one mark and it is the page now displayed.
    arrived = sidebar_active(after)
    if arrived is None or not resolves_to_screen(arrived["text"], screen):
        return NavigationResult(
            ok=False, reason=CYCLED, steps=1,
            cursor=arrived["text"] if arrived else None,
            detail=f"cliquei mas a pagina ativa nao e {screen!r}", reading=after)

    return NavigationResult(ok=True, reason=ARRIVED, steps=1,
                            cursor=arrived["text"], reading=after)


def enter_main_menu_screen_by_count(session, screen, activate_key="enter"):
    """Reach a top-level page by COUNTING, not by watching the cursor.

    This is the reliable path, and it exists because the thing it avoids
    is broken: with focus in the sidebar there are two near-identical dark
    bars (the displayed page and the cursor) and `selection.py` only ever
    reports the page one -- so a walk that re-reads the cursor after each
    press sees the same entry forever and gives up after one step.

    What is reliable instead:

    * the entry TEXTS and their order, read straight off the screen;
    * **the list does not wrap**, so pressing `up` more times than it has
      entries parks the cursor on the top element, wherever it started.
      That gives a known anchor without needing to see the cursor at all;
    * **the top element is the circular "Setup" back arrow, NOT the first
      menu entry** -- so entry *i* is `i + 1` presses of `down` below the
      anchor. Calibrated on real hardware 2026-08-24: anchored at the top,
      a single `down` then ENTER opens Main, the first entry.
    * after ENTER the ambiguity is gone -- the cursor and the displayed
      page are the same entry, leaving exactly one dark bar, which is the
      case `selection.py` reads correctly. That is what verifies arrival.

    **Why anchoring, and not just counting from where the cursor is:** an
    earlier version assumed the cursor always started one above the first
    entry. It does not -- the start depends on what happened before -- and
    when the assumption was wrong the count landed on that "Setup" back
    arrow, where ENTER opens **'Discard Changes and Exit'**. That happened
    repeatedly on the real machine before the cause was understood. So the
    cursor is driven to a known place first, and ENTER is only ever sent
    at least one step below the arrow.

    So the sequence is computed, sent, and then **checked**; it is never
    assumed to have worked.
    """
    target = labels.screen(screen)
    entries = sidebar_entries(session.read_cursor())
    if not entries:
        return NavigationResult(
            ok=False, reason=BLIND, steps=0,
            detail="nao consegui ler as entradas da barra lateral",
        )

    index = next((i for i, (_, text) in enumerate(entries)
                  if match_score(target, text)), None)
    if index is None:
        return NavigationResult(
            ok=False, reason=CYCLED, steps=0,
            visited=[text for _, text in entries],
            detail=f"{screen!r} nao esta entre as entradas lidas",
        )

    session.press("left")
    # Park on the top element. Two extra presses beyond the entry count
    # cover the back arrow above them and any miscount from an entry the
    # OCR dropped; extra presses at a hard stop are harmless.
    for _ in range(len(entries) + 2):
        session.press("up")

    # Confirm the anchor before counting from it. Without this the count
    # is only as good as the assumption that "up" reached the top, and a
    # wrong count puts ENTER on the back arrow -- which opens 'Discard
    # Changes and Exit'. Refusing to continue costs a failed tool run;
    # continuing on a bad assumption cost exactly that dialog, repeatedly,
    # on the real machine.
    anchored = setup_icon_focused(session.read_cursor().get("frame"))
    if anchored is not True:
        return NavigationResult(
            ok=False, reason=BLIND, steps=len(entries) + 3,
            detail=("nao confirmei o cursor na ancora (icone 'Setup'): "
                    + ("leitura obstruida" if anchored is None
                       else "o cursor nao esta no topo")),
        )

    for _ in range(index + 1):
        session.press("down")
    if activate_key:
        session.press(activate_key)

    # Verify against the post-ENTER single mark, not against the walk.
    after = session.read_cursor()
    if looks_like_dialog(after):
        # Never leave a dialog standing, and never answer one.
        session.press("esc")
        return NavigationResult(
            ok=False, reason=BLIND, steps=index + 2,
            detail="a sequencia abriu um dialogo de confirmacao; fechei e parei",
        )

    arrived = sidebar_active(after)
    if arrived is None or not resolves_to_screen(arrived["text"], screen):
        return NavigationResult(
            ok=False, reason=CYCLED, steps=index + 2,
            cursor=arrived["text"] if arrived else None,
            detail=f"apertei {index + 1} 'down' mas a pagina ativa nao e {screen!r}",
            reading=after,
        )

    # `reading` here is `after` -- the legacy cursor-shaped dict this
    # function already had to fetch to verify arrival, NOT a perception
    # contract. Deliberately not paying for `session.read_stable()` here
    # too: measured 2026-08-24, that extra full read cost ~1.4-1.8s on
    # top of everything else in this leg, and it is thrown away whenever
    # this leg is not the last one in a route -- `Tool.run` overwrites
    # `reading` for every leg after this one. Only the LAST leg's reading
    # actually reaches a `Reader`, so only it should ever pay for the full
    # contract; see registry.py's nav_menu branch, which re-fetches it
    # exactly once, only when the loop is done.
    return NavigationResult(
        ok=True, reason=ARRIVED, steps=index + 2, cursor=arrived["text"],
        reading=after,
    )


NAV_MODES = ("keyboard", "mouse", "auto")


def enter_main_menu_screen(session, screen, activate_key="enter", max_steps=20,
                           mode="keyboard", click_settle_delay=0.0):
    """Get to a top-level sidebar screen (Main/Advanced/Security/...), from
    wherever the BIOS currently is, and open it.

    `mode` picks which of the two paths below actually drives the
    machine -- an operator's own choice, not a fallback the code decides
    on its own:

    * `"keyboard"` -- the counted walk only. The default, because it is
      the one measured reliable on real hardware (see the timing
      comparison below).
    * `"mouse"` -- the click path only, skipping the counted walk
      entirely. For a BIOS or a moment where the keyboard path is known
      to misbehave, or simply to test the pointer path on its own.
    * `"auto"` -- keyboard first, and only if that fails, the click path
      as a fallback. This is the one place both are combined.

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

    `screen` is a canonical name from `labels.SCREENS`.

    **`activate_key` defaults to "enter" because this BIOS needs it.** An
    earlier version defaulted to None, documenting that "moving the cursor
    to a sidebar entry already switches the displayed page" -- that was
    measured wrong and was the single biggest reason tools could not reach
    a screen from an arbitrary starting page. Photographed live
    (2026-08-24, captures/handshake/): with the page showing Main and the
    cursor walked onto another entry, the sidebar draws **two** dark bars
    at once -- one on the displayed page, one on the cursor -- and the
    content panel keeps showing Main until ENTER is pressed. Without the
    ENTER the caller lands on the right sidebar row and the wrong page,
    then reads that wrong page's content and reports the answer missing.

    The walk also tries **both directions**, because this sidebar does not
    wrap: walked downward from Main the cursor stops dead on 'Event Log'
    (confirmed live -- eight further presses changed nothing), so a target
    above the starting point is unreachable by pressing "down" alone. The
    reverse pass is what makes "from wherever the BIOS currently is"
    actually true rather than aspirational.
    """
    # Counting from a verified anchor is the ONLY path. There used to be a
    # cursor-watching walk as a fallback, and it was actively dangerous
    # here: it cannot tell the sidebar's cursor bar from its active-page
    # bar, so with the page already on the target it concluded "arrived"
    # in zero steps and pressed ENTER -- while the cursor was actually
    # parked on the back arrow, where ENTER opens 'Discard Changes and
    # Exit'. That is precisely how that dialog kept appearing on the real
    # machine. A walk that cannot see what it is walking is not a fallback,
    # it is a blind keypress with a confident-looking result.
    #
    # Failing here is the correct outcome when the anchor cannot be
    # confirmed: the caller gets "could not get there", nothing is opened,
    # and no key lands on the arrow.
    # **Keyboard is the default, and the pointer path is opt-in via
    # `mode`.** The pointer path is more PORTABLE in principle -- it
    # encodes none of this BIOS's sidebar quirks, so it is the likelier
    # survivor on an unseen model -- and that argued for trying it first.
    # The measurements did not support it: back to back on real hardware
    # the counted keyboard walk reached its target in ~4s while the click
    # path spent ~14s and still failed its own arrival check ("cliquei mas
    # a pagina ativa nao e 'advanced'"). Portability is a bet on a machine
    # we have not met; reliability here is measured on the one in front of
    # us, and the measured thing wins the default. Revisit when the click
    # path holds up repeatedly, or when a third BIOS model actually breaks
    # the counted walk and makes the bet concrete.
    if mode not in NAV_MODES:
        raise ValueError(f"modo de navegacao desconhecido: {mode!r} "
                         f"(esperado um de {NAV_MODES})")

    outcome = None
    if mode in ("keyboard", "auto"):
        outcome = enter_main_menu_screen_by_count(
            session, screen, activate_key=activate_key)
        if outcome.ok:
            return outcome, outcome.reading
        if mode == "keyboard":
            return outcome, None

    # `getattr`, not attribute access: a session stand-in that does not
    # model an actuator (the offline suite's `FakeBios`) has no pointer by
    # definition and should simply not get this branch.
    if getattr(session, "actuator", None) is None:
        return outcome or NavigationResult(
            ok=False, reason=BLIND, steps=0,
            detail="sem atuador -- nao ha como mover o ponteiro"), None

    clicked = enter_main_menu_screen_by_click(
        session, screen, settle_delay=click_settle_delay)
    return clicked, (clicked.reading if clicked.ok else None)


# Phrases that mean the screen is asking to commit or abandon something,
# rather than showing a settings page. Matched on normalised text, so
# spacing and OCR punctuation noise do not matter.
_DIALOG_PHRASES = (
    "quitwithoutsaving", "discardchanges", "savechanges",
    "saveconfiguration", "exitwithoutsaving", "loaddefault",
)


def looks_like_dialog(reading):
    """True when a confirmation dialog is on screen.

    Exists because ESC is not uniformly "go up one level" on this BIOS:
    pressed at the top level it opens **'Discard Changes and Exit -- Quit
    without saving?'**, with Ok and Cancel. Observed twice for real on
    2026-08-24, both times because a tool's cleanup sent ESCs without
    looking. Anything that sends ESC in a loop has to be able to notice
    this and stop, or it will eventually send the ENTER that answers it.

    Two independent signals, either sufficient: a known phrase, or an
    Ok/Cancel pair (which no settings page shows). Deliberately eager --
    a false positive merely stops cleanup early and leaves the BIOS a
    level deep, while a false negative risks confirming an exit.
    """
    texts = {normalize(line["text"])
             for block in reading.get("blocks", ())
             for line in block.get("lines", ())}
    if any(p in t for t in texts for p in _DIALOG_PHRASES):
        return True
    return "ok" in texts and "cancel" in texts


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
