"""Scan a whole BIOS page by scrolling, then click anything on it by name.

The architecture the user proposed, and the reason it is worth having: a
tool that clicks OCR-found text does not need to know a BIOS's structure
in advance (which key walks which panel, whether a list wraps, where the
back arrow sits). All of that is hard-won, model-specific knowledge baked
into the keyboard path -- see docs/specs/f-specs/navegacao-ancorada-barra-
lateral.md for how much of it there is. Point-and-click needs none of it.

Two roles, each playing to its strength:

* **Keyboard scrolls.** PgDn/PgUp move a whole screenful at a time and
  reliably stop at the ends -- confirmed live 2026-08-24 on the Main page,
  which holds 73 unique lines against ~31 visible at once, so most of it
  is invisible without scrolling.
* **Mouse acts.** One click activates whatever is under it, with no
  counting and no assumptions about menu order.

**The load-bearing detail: a coordinate is only valid at the scroll
position it was captured at.** 'Access Level' at y=592 on screen 3 is a
different row at y=592 on screen 0. So the map stores `screen_index`
alongside x/y, and clicking means *first scrolling back to that screen*,
then aiming. Storing bare coordinates would produce confident clicks on
the wrong row.

    py -3.13 study_scroll_map.py --serial-port COM3
    py -3.13 study_scroll_map.py --serial-port COM3 --click "Device Control"
"""
import argparse

from biostools.navigate import SIDEBAR_MAX_X, looks_like_dialog
from biostools.screen import match_score
from biostools.session import BiosSession
from ocr import DEFAULT_ENGINE, ENGINE_CHOICES
from study_mouse_navigation import MouseTracker

MAX_SCREENS = 12  # generous cap; real pages have settled by 4-5


def content_lines(reading):
    """Content-panel lines only -- the sidebar does not scroll with the
    page, so including it would make every screen look partly identical
    and confuse both the bottom detection and the map.
    """
    return [line for block in reading.get("blocks", ())
            for line in block.get("lines", ())
            if line["bbox"]["left"] >= SIDEBAR_MAX_X and line["text"].strip()]


def stable_signature(lines):
    """What this screen shows, ignoring text that changes on its own.

    A live clock or a ticking sensor value makes two reads of the SAME
    scroll position look different, which reads as "still scrolling" and
    never terminates. Measured live: a first attempt at bottom-detection
    reported the Main page as scrolling when the only delta was
    `10:02:09` -> `10:02:12`.
    """
    out = set()
    for line in lines:
        text = line["text"].strip()
        digits = sum(c.isdigit() for c in text)
        if text and digits * 2 < len(text):
            out.add(text)
    return out


def scan_page(session, max_screens=MAX_SCREENS, verbose=True):
    """Scroll from wherever we are to the bottom, mapping every row.

    Returns a list of screens: `[{index, signature, lines}]`, where each
    line keeps its bbox **as seen at that scroll position**.

    Scrolls to the top first. An earlier version started from wherever the
    page happened to be and only mapped downward, which meant "map the
    whole page" silently returned a partial map whenever the caller was
    already part-way down -- observed immediately in testing: run twice in
    a row and the second run reports one screen and 25 lines against the
    first run's five screens and 73. PgUp past the top is harmless (the
    page just stops), so the cost of being sure is a fraction of a second.
    """
    for _ in range(max_screens + 2):
        session.press("pageup")

    screens = []
    previous = None
    for index in range(max_screens):
        reading = session.read_cursor()
        lines = content_lines(reading)
        signature = stable_signature(lines)

        if signature == previous:
            if verbose:
                print(f"  tela {index}: identica a anterior -> fim da pagina")
            break
        screens.append({"index": len(screens), "signature": signature,
                        "lines": lines})
        if verbose:
            new = len(signature - set().union(*(s["signature"] for s in screens[:-1]))
                      ) if len(screens) > 1 else len(signature)
            print(f"  tela {len(screens)-1}: {len(lines)} linhas ({new} novas)")
        previous = signature
        session.press("pagedown")
    return screens


def scroll_to_screen(session, index, total_screens):
    """Return to a given screen index, from anywhere.

    PgUp past the top is harmless (the page just stops), so going all the
    way up first and then down `index` times is both simple and robust --
    no need to track where the page currently sits. Overshooting up by a
    couple of presses costs a fraction of a second and removes an entire
    class of off-by-one bug.
    """
    for _ in range(total_screens + 2):
        session.press("pageup")
    for _ in range(index):
        session.press("pagedown")


def find_in_map(screens, target_text):
    """(screen_index, line) for the best match, or None.

    Prefers an exact normalised match over a containment one, same rule
    `screen.match_score` encodes -- 'Main' is a substring of 'Domain', and
    on a page mapped across several screens there are simply more chances
    for a loose match to win over the right one.
    """
    best = None
    for screen in screens:
        for line in screen["lines"]:
            score = match_score(target_text, line["text"])
            if score and (best is None or score > best[0]):
                best = (score, screen["index"], line)
    if best is None:
        return None
    return best[1], best[2]


def click_in_map(session, tracker, screens, target_text, verbose=True,
                 dry_run=False):
    """Scroll back to where the target lives, then click it.

    `dry_run` stops after aiming, without clicking. Worth having as a
    first-class mode rather than a debugging afterthought: the hard,
    novel part of this design is *scrolling back and re-locating*, and
    that can be proven completely without committing an irreversible
    click on a real machine. Clicking an arbitrary mapped row is not
    automatically safe -- it may open an editor or a dropdown -- so being
    able to validate the mechanism separately from the commit is what
    makes it testable at all on hardware that matters.
    """
    found = find_in_map(screens, target_text)
    if found is None:
        if verbose:
            print(f"  '{target_text}' nao esta no mapa -- nao vou clicar as cegas")
        return False
    index, line = found
    bbox = line["bbox"]
    if verbose:
        print(f"  '{line['text']}' esta na tela {index}, bbox={bbox}")

    scroll_to_screen(session, index, len(screens))

    # Re-read after scrolling and re-locate the target: the row's y may
    # differ by a few pixels from the mapped value (OCR jitter, or a
    # scroll that lands a hair differently than when mapped). The map says
    # WHICH screen; the fresh read says exactly WHERE, and only the fresh
    # read is trusted for the actual click.
    fresh = find_in_map([{"index": index, "lines": content_lines(session.read_cursor())}],
                        target_text)
    if fresh is None:
        if verbose:
            print(f"  rolei ate a tela {index} mas '{target_text}' nao esta la "
                  f"-- nao vou clicar")
        return False
    bbox = fresh[1]["bbox"]

    target_x = bbox["left"] + min(30, bbox["width"] * 0.3)
    target_y = bbox["top"] + bbox["height"] / 2
    if not tracker.move_to(target_x, target_y):
        if verbose:
            print("  mouse nao convergiu -- nao vou clicar")
        return False

    if dry_run:
        if verbose:
            print(f"  [dry-run] mirado em ({target_x:.0f},{target_y:.0f}) "
                  f"sobre '{fresh[1]['text']}' -- NAO cliquei")
        return True

    session.actuator.mouse_click("left")
    session._dirty = True
    after = session.read_cursor()
    if looks_like_dialog(after):
        session.press("esc")
        if verbose:
            print("  o clique abriu um dialogo -- fechei e parei")
        return False
    if verbose:
        print("  clicado.")
    return True


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--camera-source", default="0")
    parser.add_argument("--engine", choices=ENGINE_CHOICES, default=DEFAULT_ENGINE)
    parser.add_argument("--resolution", default="1280x720")
    parser.add_argument("--serial-port", required=True)
    parser.add_argument("--click", help="Texto para clicar apos mapear")
    parser.add_argument("--dry-run", action="store_true",
                        help="Mira no alvo mas nao clica -- prova o mecanismo "
                             "de rolar-e-relocalizar sem cometer nada")
    return parser.parse_args()


def main():
    args = parse_args()
    resolution = tuple(int(v) for v in args.resolution.lower().split("x"))

    with BiosSession(camera_source=args.camera_source, engine=args.engine,
                      resolution=resolution,
                      serial_port=args.serial_port) as session:
        print("mapeando a pagina inteira (PgDn ate o fim)...")
        screens = scan_page(session)
        total = set().union(*(s["signature"] for s in screens)) if screens else set()
        print(f"\n{len(screens)} tela(s), {len(total)} linhas unicas no total")

        if args.click:
            print(f"\nprocurando '{args.click}' no mapa...")
            tracker = MouseTracker(session)
            tracker.calibrate()
            click_in_map(session, tracker, screens, args.click,
                         dry_run=args.dry_run)


if __name__ == "__main__":
    main()
