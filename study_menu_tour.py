"""Visit every top-level menu, and learn to recognise each one by CONTENT.

The training run this project actually needs. Today a tool can only reach
a screen it is already near, because crossing the sidebar depends on
reading which entry is highlighted -- and that signal is the unreliable
one (see docs/specs/p-specs/deteccao-cursor-barra-lateral-instavel-entre-
frames.md: four different visual patterns, one of which shows nothing at
all).

**The premise here is the inverse: identify the page by what it SAYS, not
by what is highlighted.** Content text is the half of this pipeline that
has always worked -- every shipping tool reads its answer from it. A
BIOS page's body text is also far more distinctive than one highlighted
word: 'System Information' only appears on Main, the submenu list only on
Advanced. So a tour that walks the sidebar and fingerprints each page as
it arrives produces exactly what robust navigation needs: a way to answer
"where am I?" that does not depend on the flaky highlight at all.

Safety, deliberately narrow:

* Navigation goes through `navigate.enter_main_menu_screen`, which anchors
  the cursor on the sidebar's top "Setup" back arrow, verifies that anchor
  by looking at the icon, and only then counts down to the wanted entry.
  It refuses to press ENTER when the anchor cannot be confirmed.
* **'save_and_exit' is not visited by default.** Displaying it is
  harmless, but every control on that page commits or abandons
  configuration, so a training run has no business leaving a cursor
  there. Pass it in --menus explicitly if you mean it.
* Nothing here can change a setting: no `+`/`-`, no F-keys.

    py -3.13 study_menu_tour.py --serial-port COM3

Output: a per-page content fingerprint saved to
`captures/menu_tour_<timestamp>/`, plus a frame of each page, which is
the raw material for a content-based "which screen is this?" resolver.
"""
import argparse
import json
import os
import time

import cv2

from biostools.navigate import SIDEBAR_MAX_X, enter_main_menu_screen
from biostools.screen import normalize
from biostools.session import BiosSession
from ocr import DEFAULT_ENGINE, ENGINE_CHOICES

SAFE_KEYS = ("up", "down", "left", "right")

# Two readings of the same page never match exactly -- OCR drops or
# mangles a glyph here and there, and a page with a clock changes on its
# own. Two pages, on the other hand, share almost nothing but the chrome.
# Measured on this BIOS the gap is wide, so the exact cut is not delicate.
SAME_PAGE_SIMILARITY = 0.6


def is_volatile(token):
    """Text that changes with no keypress involved: clocks, sensor values.

    Without this the Main page's live clock makes every reading of it look
    like a different page (measured: flipping only 16:30:48 -> :49 changed
    the engine's whole content fingerprint).
    """
    if not token:
        return True
    digits = sum(c.isdigit() for c in token)
    return digits * 2 >= len(token)


def page_fingerprint(reading):
    """The stable, content-side vocabulary of whatever page is displayed."""
    lines = [l for b in reading.get("blocks", ()) for l in b.get("lines", ())]
    content = [l for l in lines if l["bbox"]["left"] >= SIDEBAR_MAX_X]
    return {t for t in (normalize(l["text"]) for l in content)
            if t and not is_volatile(t)}


def sidebar_texts(reading):
    lines = [l for b in reading.get("blocks", ()) for l in b.get("lines", ())]
    return [l["text"] for l in lines if l["bbox"]["left"] < SIDEBAR_MAX_X]


def sidebar_mark(reading):
    """The highlighted sidebar entry, or None. Recorded, never trusted.

    Kept alongside the content fingerprint precisely so the tour measures
    how often this signal agrees with the reliable one -- that comparison
    is the point, so it must not be used to drive the walk.
    """
    lines = [l for b in reading.get("blocks", ()) for l in b.get("lines", ())]
    marked = [l for l in lines
              if l["bbox"]["left"] < SIDEBAR_MAX_X and l.get("highlighted")]
    return marked[0]["text"] if len(marked) == 1 else None


def similarity(a, b):
    """Jaccard overlap of two fingerprints."""
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def name_page(fingerprint, sidebar_entries):
    """Best-effort human label for a page, from its own content.

    A BIOS page usually titles itself, or names its own section, somewhere
    in the body. Falls back to the longest distinctive token so a page
    still gets a stable-ish handle even when nothing looks like a title.
    Sidebar words are excluded: they appear on every page and so identify
    none of them.
    """
    banned = {normalize(t) for t in sidebar_entries}
    candidates = [t for t in fingerprint if t not in banned and len(t) > 6]
    if not candidates:
        return "?"
    return sorted(candidates, key=lambda t: (-len(t), t))[0][:40]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--camera-source", default="0")
    parser.add_argument("--engine", choices=ENGINE_CHOICES, default=DEFAULT_ENGINE)
    parser.add_argument("--resolution", default="1280x720")
    parser.add_argument("--serial-port", required=True)
    parser.add_argument("--key", default="down", choices=SAFE_KEYS,
                        help="Direction to walk the sidebar")
    parser.add_argument("--focus-key", default="left", choices=SAFE_KEYS,
                        help="Pressed once up front to hand focus to the sidebar")
    # 'save_and_exit' is deliberately NOT in the default list. Merely
    # displaying that page is harmless, but it is the one page whose every
    # control commits or abandons configuration, so a training run has no
    # business parking a cursor there. Pass it explicitly if you mean it.
    parser.add_argument("--menus",
                        default="main,advanced,security,boot,event_log",
                        help="Canonical screen names to visit, in order "
                             "(see biostools/labels.py SCREENS)")
    parser.add_argument("--steps", type=int, default=8,
                        help="Unused by the menu list walk; kept for the "
                             "older free-walk invocation")
    parser.add_argument("--out-dir", default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    resolution = tuple(int(v) for v in args.resolution.lower().split("x"))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or os.path.join("captures", f"menu_tour_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    print("passeio pelos menus -- SO setas, nenhum enter, nenhum esc.")
    print(f"foco: {args.focus_key!r}   caminhada: {args.key!r}   "
          f"passos: {args.steps}\n")

    visited = []   # one entry per distinct page, in the order first seen
    timeline = []  # one entry per step, including repeats

    with BiosSession(camera_source=args.camera_source, engine=args.engine,
                      resolution=resolution,
                      serial_port=args.serial_port) as session:
        for step, screen_name in enumerate(args.menus.split(",")):
            screen_name = screen_name.strip()
            if not screen_name:
                continue
            outcome, _ = enter_main_menu_screen(session, screen_name)
            if not outcome.ok:
                print(f"[{step}] {screen_name}: NAO CHEGUEI -- {outcome.reason} "
                      f"({outcome.detail})")
                continue

            reading = session.read_cursor()
            frame = reading.get("frame")
            fingerprint = page_fingerprint(reading)
            entries = sidebar_texts(reading)
            mark = sidebar_mark(reading)

            known = None
            for page in visited:
                if similarity(fingerprint, page["fingerprint"]) >= SAME_PAGE_SIMILARITY:
                    known = page
                    break

            if known is None:
                label = name_page(fingerprint, entries)
                known = {"index": len(visited), "label": label,
                         "fingerprint": fingerprint, "marks": [], "steps": []}
                visited.append(known)
                status = "PAGINA NOVA"
                if frame is not None:
                    cv2.imwrite(os.path.join(out_dir,
                                             f"page{known['index']:02d}.png"), frame)
            else:
                status = f"ja vista (pagina {known['index']})"

            known["marks"].append(mark)
            known["steps"].append(step)
            timeline.append({"step": step, "menu": screen_name,
                             "page": known["index"],
                             "label": known["label"], "sidebar_mark": mark})

            print(f"[{step}] {screen_name}: pagina {known['index']} "
                  f"<{known['label']}>  {status}")
            print(f"     destaque na barra: {mark!r}"
                  f"   ({len(fingerprint)} termos de conteudo)")

    # -- what the tour learned --------------------------------------------
    print("\n" + "=" * 62)
    print(f"{len(visited)} pagina(s) distinta(s) em {args.steps} movimento(s):\n")
    for page in visited:
        marks = [m for m in page["marks"] if m]
        agreement = f"{len(marks)}/{len(page['marks'])}"
        print(f"  pagina {page['index']} <{page['label']}>")
        print(f"     vista nos passos {page['steps']}")
        print(f"     destaque legivel em {agreement} das visitas: "
              f"{sorted(set(marks)) or 'nunca'}")

    print()
    if len(visited) <= 1:
        print("NENHUMA troca de pagina: a caminhada nao esta mexendo na barra "
              "lateral. Ou o foco nao foi para a barra, ou a tecla nao chegou. "
              "Este e o modo de falha que bloqueia as tools hoje.")
    else:
        # The number worth having: how often the unreliable signal was
        # readable at all, across pages the content proved we reached.
        total = sum(len(p["marks"]) for p in visited)
        readable = sum(1 for p in visited for m in p["marks"] if m)
        print(f"O conteudo identificou a pagina em {total}/{total} leituras; "
              f"o destaque da barra so foi legivel em {readable}/{total}.")
        print("E exatamente por isso que a navegacao deve se ancorar no "
              "conteudo, nao no destaque.")

    payload = [{"index": p["index"], "label": p["label"],
                "fingerprint": sorted(p["fingerprint"]),
                "sidebar_marks": p["marks"], "steps": p["steps"]}
               for p in visited]
    with open(os.path.join(out_dir, "pages.json"), "w", encoding="utf-8") as f:
        json.dump({"timeline": timeline, "pages": payload}, f,
                  indent=2, ensure_ascii=False)
    print(f"\nimpressoes digitais e frames salvos em {out_dir}")


if __name__ == "__main__":
    main()
