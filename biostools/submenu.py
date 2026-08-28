"""Reaching a screen ONE LEVEL BELOW a top-level page, by name.

`navigate.enter_main_menu_screen` gets to any of the six sidebar screens.
Everything worth reading on this BIOS that is not on Main lives one level
further down -- Trusted Computing, Device Control, Network Stack, MAPT,
Smart Charging, TLS Auth, PAP and Hardware Monitor are all inside
Advanced -- and until now the only way to reach one was a hand-written
`Tool` with `Step(to=..., hint="settings_list")` in its route. Eight
submenus meant eight tools, and a question about the ninth had no answer
at all.

This module is that step written once, with the destination chosen at
call time:

    outcome = enter_submenu(session, "hardware_monitor")

**Two declarations gate it, and neither is optional.** `labels.SUBMENUS`
says which submenu lives under which top-level screen -- a name absent
from that map is never attempted, so nothing here can wander into a page
nobody declared. `labels.SCREENS` says how the entry is spelled -- the
item is found by matching those spellings through `screen.match_score`,
never by position in the list, and never by "the closest-looking line".
An Advanced page that words the entry differently produces a clean "não
encontrei o submenu", not a confident ENTER on the wrong row.

**Arrival is verified, not assumed** (R5). The ENTER is only believed
when the screen that comes back actually carries a declared spelling of
the destination.

`save_and_exit` is refused as destination and as parent, before any key
is sent. Read-only throughout: every key here is in
`registry.SAFE_KEYS`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import labels
from . import screen as screen_mod
from .navigate import (
    TOP_LEVEL_SCREENS, activate, enter_main_menu_screen, looks_like_dialog,
    move_to,
)
from .page import MAX_SCREENS, content_lines, find_line, reposition, scan_page

CONFIRMADO = "CONFIRMADO"
PALPITE = "palpite"

# The one sentence a `palpite` result must carry, so every caller reports
# the same thing and a test can assert on it.
UNCONFIRMED_NOTE = ("submenu nao confirmado em hardware "
                    "(provenance=palpite em labels.SUBMENUS)")

# Reasons, named so a caller branches on the name instead of on prose.
ARRIVED = "arrived"
UNKNOWN_SUBMENU = "unknown_submenu"
FORBIDDEN = "forbidden_screen"
PARENT_UNREACHABLE = "parent_unreachable"
NOT_ON_PAGE = "submenu_not_on_page"
NOT_VERIFIED = "arrival_not_verified"

# Why F3/F4 declined, kept verbatim because the tests and the index
# header both quote it.
REASON_PALPITE = "provenance=palpite"
REASON_UNDECLARED = "grafia nao declarada"


@dataclass
class SubmenuResult:
    ok: bool
    reason: str
    steps: int = 0
    detail: str | None = None
    notes: list = field(default_factory=list)
    reading: object = None
    submenu: str | None = None
    parent: str | None = None
    provenance: str | None = None
    opened: int = 0


def is_confirmed(submenu):
    """True only for a submenu a human has marked CONFIRMADO.

    The single place that decides it, so the F3/F4/K6 rules of CA-F2.1a
    cannot drift apart by each re-reading the table its own way.
    """
    return (submenu in labels.SUBMENUS
            and labels.SUBMENUS[submenu]["provenance"] == CONFIRMADO)


def confirmed_submenus(parent=None):
    """Submenus a human confirmed on real hardware -- the K6 population."""
    return sorted(name for name in labels.SUBMENUS
                  if is_confirmed(name)
                  and (parent is None
                       or labels.SUBMENUS[name]["parent"] == parent))


def skip_reason(submenu):
    """Why F3/F4 must not go there, or None when they may.

    Two different refusals, kept distinct because they call for different
    human actions: `grafia nao declarada` means someone has to run the
    harvest and read a dump, while `provenance=palpite` means the dump
    already exists and someone has to review and promote it.
    """
    if submenu not in labels.SUBMENUS:
        return REASON_UNDECLARED
    try:
        labels.screen(submenu)
    except labels.UnknownLabel:
        return REASON_UNDECLARED
    if not is_confirmed(submenu):
        return REASON_PALPITE
    return None


def _locate(session, spellings, max_screens):
    """(screen_index, line, scan) for the submenu entry on this page.

    Looks at the screenful already in front of us first. Only if the entry
    is not there does it pay for a full scrolled scan -- a page-at-a-time
    scan costs a read and a key press per screenful, and most submenu
    entries on this BIOS sit above the fold. When the scan IS needed, it
    is F1 doing it (CA-F2.5), so an entry below the fold is reachable
    rather than reported missing.
    """
    reading = session.read_stable()
    lines = content_lines(reading)
    best = None
    for line in lines:
        score = screen_mod.match_score(spellings, line["text"])
        if score and (best is None or score > best[0]):
            best = (score, line)
    if best is not None:
        return 0, best[1], None

    scan = scan_page(session, max_screens=max_screens)
    found = find_line(scan, spellings)
    if found is None:
        return None, None, scan
    return found[0], found[1], scan


def enter_submenu(session, submenu, mode="keyboard", restore=False,
                  max_screens=MAX_SCREENS):
    """Go to `submenu`'s parent screen, then open `submenu`. P3 of the specs.

    `restore=True` sends the ESC that closes what was opened, so two calls
    in a row work -- the same repeatability problem `Tool.run`'s
    `_close_opened` exists for (`cpu_temperature` used to succeed exactly
    once per session, because it left the BIOS inside Hardware Monitor
    where that entry no longer exists in the list).

    A `palpite` submenu is navigated -- an operator naming a destination
    by hand is allowed to try one -- but the result says so in `notes`.
    F3 and F4 must not call this without checking `skip_reason` first;
    that asymmetry is CA-F2.1a and it is deliberate, not an oversight.
    """
    try:
        parent = labels.submenu_parent(submenu)
    except labels.UnknownLabel as e:
        return SubmenuResult(ok=False, reason=UNKNOWN_SUBMENU, submenu=submenu,
                             detail=str(e))

    if submenu == "save_and_exit" or parent == "save_and_exit":
        return SubmenuResult(
            ok=False, reason=FORBIDDEN, submenu=submenu, parent=parent,
            detail="'save_and_exit' nao e visitada por nenhum caminho "
                   "automatico -- todo controle dela confirma ou descarta "
                   "configuracao. Fronteira deliberada (R6).",
        )

    try:
        spellings = labels.screen(submenu)
    except labels.UnknownLabel as e:
        return SubmenuResult(ok=False, reason=UNKNOWN_SUBMENU, submenu=submenu,
                             parent=parent, detail=str(e))

    provenance = labels.submenu_provenance(submenu)
    notes = [] if provenance == CONFIRMADO else [UNCONFIRMED_NOTE]

    if parent not in TOP_LEVEL_SCREENS:
        return SubmenuResult(
            ok=False, reason=UNKNOWN_SUBMENU, submenu=submenu, parent=parent,
            provenance=provenance, notes=notes,
            detail=f"o pai declarado {parent!r} nao e uma tela da barra "
                   f"lateral (conhecidas: {', '.join(sorted(TOP_LEVEL_SCREENS))})",
        )

    outcome, _ = enter_main_menu_screen(session, parent, mode=mode)
    steps = outcome.steps
    if not outcome.ok:
        return SubmenuResult(
            ok=False, reason=PARENT_UNREACHABLE, steps=steps, submenu=submenu,
            parent=parent, provenance=provenance, notes=notes,
            detail=f"nao cheguei em {parent!r}: {outcome.reason}"
                   + (f" ({outcome.detail})" if outcome.detail else ""),
        )
    opened = 1

    index, line, scan = _locate(session, spellings, max_screens)
    if line is None:
        _restore(session, opened, restore)
        return SubmenuResult(
            ok=False, reason=NOT_ON_PAGE, steps=steps, submenu=submenu,
            parent=parent, provenance=provenance, notes=notes,
            opened=0 if restore else opened,
            detail=f"nao encontrei o submenu {submenu!r} na pagina {parent!r} "
                   f"(grafias declaradas: {spellings}) -- nenhuma linha casou, "
                   f"e casar com a mais parecida nao e uma opcao",
        )

    # Scrolled to find it: come back to the screenful it lives on before
    # walking the cursor, because a cursor walk is counted from where the
    # page is NOW and the scan left the page at its bottom.
    if scan is not None:
        page = {"page_id": f"{parent}:{submenu}",
                "total_screens": scan.total_screens,
                "signatures": {str(k): v for k, v in scan.signatures().items()}}
        ok, detail = reposition(session, page, index)
        if not ok:
            _restore(session, opened, restore)
            return SubmenuResult(
                ok=False, reason=NOT_ON_PAGE, steps=steps, submenu=submenu,
                parent=parent, provenance=provenance, notes=notes,
                detail=detail,
            )
        notes.append(f"submenu estava abaixo da dobra: screenful {index}")

    walked = move_to(session, spellings, hint="settings_list", key="down")
    steps += walked.steps
    if not walked.ok:
        _restore(session, opened, restore)
        return SubmenuResult(
            ok=False, reason=NOT_ON_PAGE, steps=steps, submenu=submenu,
            parent=parent, provenance=provenance, notes=notes,
            detail=f"vi {line['text']!r} na pagina mas nao consegui pousar o "
                   f"cursor nele: {walked.reason}"
                   + (f" ({walked.detail})" if walked.detail else ""),
        )

    reading = activate(session, "enter")
    steps += 1
    opened += 1

    if not _arrived(reading, spellings):
        _restore(session, opened, restore)
        return SubmenuResult(
            ok=False, reason=NOT_VERIFIED, steps=steps, submenu=submenu,
            parent=parent, provenance=provenance, notes=notes, reading=reading,
            detail=f"apertei enter sobre {line['text']!r} mas nao confirmei a "
                   f"chegada: nenhuma grafia declarada de {submenu!r} "
                   f"({spellings}) esta na tela resultante",
        )

    if restore:
        _restore(session, opened, restore)
        opened = 0

    return SubmenuResult(ok=True, reason=ARRIVED, steps=steps, submenu=submenu,
                         parent=parent, provenance=provenance, notes=notes,
                         reading=reading, opened=opened)


def _arrived(reading, spellings):
    """True when a declared spelling of the destination is on screen."""
    for line in content_lines(reading):
        if screen_mod.match_score(spellings, line["text"]):
            return True
    return False


def _restore(session, opened, restore):
    """One ESC per ENTER, looking between each -- same discipline as
    `registry._close_opened`, and for the same reason: ESC at the top
    level of this BIOS opens 'Discard Changes and Exit' rather than going
    up, so a blind run of ESCs is not safe cleanup."""
    if not restore:
        return
    for _ in range(opened):
        session.press("esc")
        if looks_like_dialog(session.read_cursor()):
            session.press("esc")
            return


def confirmed_without_evidence(raw_labels):
    """KPI K12: submenus marked CONFIRMADO with no raw line to back it.

    `raw_labels` is `{screen: [line, ...]}` as loaded from
    `data/raw_labels/`. Returns the offending canonical names -- the
    metric's target is an empty list, and it is what stops the CONFIRMADO
    mark from being applied on a hunch. A `palpite` entry is not checked:
    it claims nothing, so it owes no evidence.
    """
    texts = [line.get("text", "")
             for lines in raw_labels.values() for line in lines]
    missing = []
    for name in sorted(labels.SUBMENUS):
        if not is_confirmed(name):
            continue
        spellings = labels.screen(name)
        if not any(screen_mod.match_score(spellings, text) for text in texts):
            missing.append(name)
    return missing
