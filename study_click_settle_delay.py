"""Does waiting longer after a page changes, before the NEXT click, fix
the intermittent mouse-click drops on the sidebar?

Two independent measurements on 2026-08-27 pointed the same way without
proving it:

1. Aiming the click at the blank margin of a sidebar row (instead of on
   top of the OCR text, which has a jittery edge) raised the hit rate
   from ~2-3/6 to 4/6 on the first run, but a second, larger run (3/8)
   brought the combined rate back down to ~50% (7/14) -- a real fix for
   one source of fragility, but not the dominant one.
2. A side-by-side comparison against the perception engine showed the
   legacy `selection.py` detector was reading the real screen correctly
   the whole time -- when it reported "still on Boot", the page genuinely
   had not changed. So the failures are not misreads; the click itself is
   not registering, for several attempts in a row, then working again.

That "several in a row, then fine" shape is the tell: if each click were
an independent coin flip, failures would scatter randomly across a run
instead of clumping. A clump looks like a STATE that gets entered and
persists (e.g. the BIOS not yet listening for pointer input right after a
redraw) rather than per-click noise. `session.wait_stable()` only proves
the IMAGE stopped changing; it says nothing about whether input handling
has caught up.

This script tests the direct, cheap fix for that hypothesis: pause a
configurable number of seconds after arriving on a page -- i.e. right
before the NEXT click is sent -- via `settle_delay` on
`enter_main_menu_screen_by_click`. Run once with `--delay 0` to
reproduce today's ~50% baseline, then again with a larger delay (start
around 1.0-1.5s) and compare both the success rate AND the length of the
longest run of consecutive failures. If the delay collapses the streaks
down to isolated singles (or fixes them outright), that confirms the
settle hypothesis; if long runs of failures persist even with a generous
delay, look elsewhere (e.g. the cable/actuator side, not the BIOS's
redraw timing).

Cycles through the real top-level sidebar entries in order
(main -> advanced -> security -> boot -> main -> ...), which is also a
safe loop to leave running unattended: none of these screens has a
control that commits or discards configuration, unlike 'save_and_exit'.

    py -3.13 study_click_settle_delay.py --serial-port COM3 --delay 1.5 --rounds 3
"""
import argparse
import json
import os
import time

from biostools.navigate import enter_main_menu_screen_by_click
from biostools.session import BiosSession
from ocr import DEFAULT_ENGINE, ENGINE_CHOICES

# 'save_and_exit' and 'event_log' deliberately excluded from the default
# cycle -- the former commits/discards configuration, the latter is not
# needed to exercise the click-settle question and only lengthens the
# loop.
DEFAULT_MENUS = ("main", "advanced", "security", "boot")


def longest_failure_run(outcomes):
    """Longest streak of consecutive False in `outcomes`. The number the
    settle hypothesis is actually about -- an overall success RATE alone
    cannot tell "50% scattered randomly" apart from "50% because half the
    runs got stuck for a few clicks in a row", and only the second shape
    supports "the BIOS enters a bad state and stays there".
    """
    longest = current = 0
    for ok in outcomes:
        current = 0 if ok else current + 1
        longest = max(longest, current)
    return longest


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--camera-source", default="0")
    parser.add_argument("--engine", choices=ENGINE_CHOICES, default=DEFAULT_ENGINE)
    parser.add_argument("--resolution", default="1280x720")
    parser.add_argument("--serial-port", required=True)
    parser.add_argument("--menus", default=",".join(DEFAULT_MENUS),
                        help="Comma-separated canonical screen names, "
                             "cycled in order")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="Seconds paused before each click, once the "
                             "pointer has already confirmed its position "
                             "(settle_delay). 0 reproduces today's baseline.")
    parser.add_argument("--rounds", type=int, default=2,
                        help="How many full passes through --menus")
    parser.add_argument("--out-dir", default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    resolution = tuple(int(v) for v in args.resolution.lower().split("x"))
    menus = [m.strip() for m in args.menus.split(",") if m.strip()]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or os.path.join(
        "captures", f"click_settle_delay_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    sequence = menus * args.rounds
    print(f"delay={args.delay}s  sequencia ({len(sequence)} cliques): "
          f"{sequence}\n")

    attempts = []
    with BiosSession(camera_source=args.camera_source, engine=args.engine,
                      resolution=resolution,
                      serial_port=args.serial_port) as session:
        for i, screen in enumerate(sequence):
            result = enter_main_menu_screen_by_click(
                session, screen, settle_delay=args.delay)
            status = "OK" if result.ok else f"FALHOU ({result.reason})"
            print(f"[{i:02d}] alvo={screen:<12s} {status}"
                  f"{'' if result.ok else '  ' + (result.detail or '')}")
            attempts.append({
                "index": i, "target": screen, "ok": result.ok,
                "reason": result.reason, "detail": result.detail,
                "cursor": result.cursor,
            })

    ok_count = sum(1 for a in attempts if a["ok"])
    streak = longest_failure_run([a["ok"] for a in attempts])

    print(f"\n{ok_count}/{len(attempts)} cliques registraram "
          f"(delay={args.delay}s)")
    print(f"maior sequencia de falhas consecutivas: {streak}")
    if streak >= 3:
        print("Falhas em sequencia longa persistem mesmo com este delay -- "
              "a hipotese de 'BIOS ainda nao esta ouvindo o mouse logo "
              "apos o redesenho' nao esta resolvida por so esperar mais; "
              "olhar para o lado do cabo/atuador em seguida.")
    elif ok_count == len(attempts):
        print("Nenhuma falha neste delay -- rode --delay 0 de novo para "
              "confirmar que o baseline ainda falha, antes de concluir "
              "que o delay resolveu.")
    else:
        print("Falhas isoladas, nao em sequencia longa -- compativel com "
              "a hipotese de estado-que-trava tendo sido mitigada por "
              "este delay.")

    with open(os.path.join(out_dir, "attempts.json"), "w",
              encoding="utf-8") as f:
        json.dump({"delay": args.delay, "menus": menus,
                   "rounds": args.rounds, "attempts": attempts}, f,
                  indent=2, ensure_ascii=False)
    print(f"\nlog salvo em {out_dir}")


if __name__ == "__main__":
    main()
