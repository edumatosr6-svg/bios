"""Colheita das grafias cruas -- o passo que quebra a circularidade de F0.

The problem, stated plainly. F2 needs a declared spelling to find a
submenu. `labels.py` forbids declaring a spelling nobody has seen on real
hardware. Seeing it requires visiting the page. Visiting the page requires
F2. Seven of the eight submenus this slug targets were in exactly that
loop -- declared nowhere, therefore unreachable, therefore never seen.

The way out is a step that reads WITHOUT matching. This module walks the
top-level screens, scrolls each page to the end (F1), and dumps **every**
content line it saw into `data/raw_labels/<screen>.json` -- text, screen,
scroll position, bbox. Nothing is compared against `labels.py`, so
nothing is filtered out for not being declared yet. That is the entire
trick: colher não exige grafia declarada.

**What this module does NOT do, on purpose: it does not write
`biostools/labels.py`.** A person reads the dump, decides which line
corresponds to which concept, and edits the table by hand. Automating
that would make the `# CONFIRMADO` mark mean "some code thought these
looked alike", which is precisely the meaning it exists to exclude --
and the mark is what every downstream guard (K12, the F3 tour, F4's
navigation) trusts. A provenance discipline that a script can satisfy
protects nothing.

It also never enters a submenu: at harvest time it cannot -- that is the
capability being bootstrapped -- and it never touches `save_and_exit`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .index import FORBIDDEN_REASON, FORBIDDEN_SCREEN
from .navigate import TOP_LEVEL_SCREENS, enter_main_menu_screen
from .page import MAX_SCREENS, scan_page

RAW_LABELS_DIR = Path("data") / "raw_labels"


def dump_from_scan(scan, screen):
    """`RawLabelDump` rows for one page: raw text plus where it was seen.

    `screen_index` travels with every row because a bbox is only valid at
    the scroll position it was captured at -- a row dumped without it
    could not be found again, which would make the dump unreviewable
    against the machine.
    """
    return [{"text": line["text"].strip(),
             "screen": screen,
             "screen_index": line["screen_index"],
             "bbox": dict(line["bbox"])}
            for line in scan.all_lines()
            if line["text"].strip()]


def harvest(session, mode="keyboard", max_screens=MAX_SCREENS,
            directory=RAW_LABELS_DIR, on_event=None):
    """P3a: dump raw content text of every top-level screen but one.

    Returns `{"written": {screen: path}, "skipped": [...], "dumps":
    {screen: rows}}`. Like the tour, a screen that cannot be reached is
    recorded and skipped rather than allowed to end the run.
    """
    directory = Path(directory)
    os.makedirs(directory, exist_ok=True)

    result = {"written": {}, "dumps": {},
              "skipped": [{"screen": FORBIDDEN_SCREEN,
                           "reason": FORBIDDEN_REASON}]}

    def emit(message):
        if on_event:
            on_event(message)

    for screen in TOP_LEVEL_SCREENS:
        if screen == FORBIDDEN_SCREEN:
            emit(f"{screen}: pulada -- {FORBIDDEN_REASON}")
            continue

        outcome, _ = enter_main_menu_screen(session, screen, mode=mode)
        if not outcome.ok:
            reason = (f"nao cheguei na tela: {outcome.reason}"
                      + (f" ({outcome.detail})" if outcome.detail else ""))
            result["skipped"].append({"screen": screen, "reason": reason})
            emit(f"{screen}: pulada -- {reason}")
            continue

        scan = scan_page(session, max_screens=max_screens)
        rows = dump_from_scan(scan, screen)
        if not rows:
            result["skipped"].append({"screen": screen,
                                      "reason": scan.error or "nenhuma linha"})
            emit(f"{screen}: pulada -- sem linhas de conteudo")
            continue

        result["dumps"][screen] = rows
        result["written"][screen] = str(write_dump(screen, rows, directory))
        emit(f"{screen}: {len(rows)} linhas cruas em "
             f"{result['written'][screen]}")

    return result


def write_dump(screen, rows, directory=RAW_LABELS_DIR):
    directory = Path(directory)
    os.makedirs(directory, exist_ok=True)
    path = directory / f"{screen}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def load_dumps(directory=RAW_LABELS_DIR):
    """`{screen: rows}` for every dump on disk. Empty dict when there are
    none -- an absent harvest is a state, not an error: it simply means
    no submenu can be promoted to CONFIRMADO yet."""
    directory = Path(directory)
    if not directory.is_dir():
        return {}
    dumps = {}
    for path in sorted(directory.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            dumps[path.stem] = json.load(f)
    return dumps
