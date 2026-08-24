"""Does the sidebar's cursor colour signal hold still across frames of a
screen that has NOT changed?

Written to answer the question `docs/specs/p-specs/deteccao-cursor-barra-
lateral-instavel-entre-frames.md` left open: on 2026-08-21, testing the
same real sidebar state repeatedly, four different visual patterns were
seen in one session -- including the same situation producing a clean
signal once and NO signal (fg=[255,255,255] uniform, nothing to compare
against a baseline) on a later attempt. That could mean either (a) the
camera sometimes captures mid-redraw, so the same real state yields
different pixels frame to frame, or (b) something about the BIOS itself
is genuinely inconsistent between reads. This script tells them apart the
only way that's conclusive: hold the keyboard still, read the identical
real screen many times in a row, and see whether `selection.py`'s verdict
changes anyway.

No cable needed -- this never presses a key. Point the camera at a
sidebar screen (any top-level page, Main/Advanced/...) and run:

    py -3.13 study_sidebar_stability.py --camera-source 0 --readings 20

Each reading is independent: `BiosSession.read_cursor()` calls
`wait_stable()` first, so this also exercises whether the stability gate
itself is letting through frames that only look settled. Frames are
saved to `captures/sidebar_stability_<timestamp>/` so a disagreement
between readings can be inspected after the fact, not just asserted from
a printed colour tuple (the project's own precedent: see
`docs/specs/p-specs/fixture-de-teste-nunca-versionada.md` for what
happens when live evidence isn't kept).
"""
import argparse
import json
import os
import time
from collections import Counter

import cv2

from biostools.navigate import SIDEBAR_MAX_X
from biostools.screen import legacy_cursor, normalize
from biostools.session import BiosSession
from ocr import DEFAULT_ENGINE, ENGINE_CHOICES


def sidebar_lines(reading):
    lines = [line for block in reading.get("blocks", ())
             for line in block.get("lines", ())]
    return [line for line in lines if line["bbox"]["left"] < SIDEBAR_MAX_X]


def snapshot(reading):
    """What one reading saw in the sidebar, reduced to what we compare
    across readings: which entry (if any) the legacy detector marked, and
    the raw per-line colour data that fed that decision.
    """
    marked = legacy_cursor(reading)
    return {
        "marked_text": marked["text"] if marked else None,
        "marked_norm": normalize(marked["text"]) if marked else None,
        "lines": [
            {
                "text": line["text"],
                "highlighted": bool(line.get("highlighted")),
                "fg_color": line.get("fg_color"),
                "bg_color": line.get("bg_color"),
            }
            for line in sidebar_lines(reading)
        ],
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--camera-source", default="0")
    parser.add_argument("--engine", choices=ENGINE_CHOICES, default=DEFAULT_ENGINE)
    parser.add_argument("--resolution", default="1280x720")
    parser.add_argument("--readings", type=int, default=20,
                        help="How many consecutive reads of the same real state")
    parser.add_argument("--interval", type=float, default=0.0,
                        help="Extra pause between readings, seconds -- 0 relies "
                             "entirely on wait_stable's own settle gate")
    parser.add_argument("--out-dir", default=None,
                        help="Where to save frames + log (default: "
                             "captures/sidebar_stability_<timestamp>/)")
    parser.add_argument("--serial-port",
                        help="COM port of the USB-KM232 cable, e.g. COM3. Only "
                             "needed for --focus-key (this script never presses "
                             "a key inside the timed loop, only once up front).")
    parser.add_argument("--focus-key",
                        help="Key to press ONCE before the loop starts, e.g. "
                             "'left' to hand focus to the sidebar.")
    parser.add_argument("--pre-keys", default="",
                        help="Comma-separated keys pressed in sequence, once, "
                             "after --focus-key and before the loop -- e.g. "
                             "'down,down' to move the cursor to an entry "
                             "different from the currently displayed page. "
                             "This is what reproduces the pattern-3/4 "
                             "instability from the P-spec: cursor (focused) "
                             "diverging from the active page (selected) is "
                             "exactly the two-signal case selection.py's "
                             "outlier cap has to arbitrate.")
    return parser.parse_args()


def main():
    args = parse_args()
    resolution = tuple(int(v) for v in args.resolution.lower().split("x"))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or os.path.join("captures", f"sidebar_stability_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    print(f"engine={args.engine} readings={args.readings} out_dir={out_dir}")
    print("Keyboard should stay untouched for the whole run.\n")

    snapshots = []
    with BiosSession(camera_source=args.camera_source, engine=args.engine,
                      resolution=resolution,
                      serial_port=args.serial_port) as session:
        if args.focus_key:
            session.press(args.focus_key)
            print(f"pressed {args.focus_key!r} once, before any reading")
        for key in filter(None, args.pre_keys.split(",")):
            session.press(key)
            print(f"pressed {key!r} once, before any reading")
        if args.focus_key or args.pre_keys:
            print()

        for i in range(args.readings):
            reading = session.read_cursor()
            shot = snapshot(reading)
            snapshots.append(shot)

            # PNG, not JPG: lossy compression measurably moves colour values
            # near a detection threshold. Confirmed 2026-08-24 -- the same
            # in-memory frame classified one way live and a different way
            # after a JPG round-trip (a borderline `Boot` line went from
            # "text-colour outlier tied with Advanced, abstain" to "distinct
            # background colour, decide alone") -- so a JPG fixture is not a
            # faithful record of what the pipeline actually saw.
            frame_path = os.path.join(out_dir, f"{i:03d}.png")
            cv2.imwrite(frame_path, reading["frame"])

            print(f"[{i:03d}] marked={shot['marked_text']!r}  "
                  f"sidebar_lines={len(shot['lines'])}")
            for line in shot["lines"]:
                flag = "*" if line["highlighted"] else " "
                print(f"       {flag} fg={line['fg_color']} "
                      f"bg={line['bg_color']}  {line['text']!r}")

            if args.interval:
                time.sleep(args.interval)

    log_path = os.path.join(out_dir, "readings.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(snapshots, f, indent=2, ensure_ascii=False)

    # -- verdict ----------------------------------------------------------
    marked_values = [s["marked_norm"] for s in snapshots]
    distinct = Counter(marked_values)
    none_count = distinct.get(None, 0)

    print(f"\n{args.readings} readings, {len(distinct)} distinct marked-entry "
          f"value(s) (including None):")
    for value, count in distinct.most_common():
        label = value if value is not None else "(nothing detected)"
        print(f"  {count:3d}x  {label}")

    if len(distinct) <= 1:
        print("\nSTABLE: every reading agreed. If this run still hit "
              "'nothing detected' every time, that's a real abstention, not "
              "jitter -- rerun with a screen where a highlight is visibly on "
              "screen to camera.")
    else:
        print("\nUNSTABLE: the same real, untouched screen produced "
              f"{len(distinct)} different verdicts across {args.readings} "
              "reads. This is the camera/timing hypothesis confirmed -- see "
              "docs/specs/p-specs/deteccao-cursor-barra-lateral-instavel-"
              "entre-frames.md. Inspect the saved frames in "
              f"{out_dir} for what differs between an agreeing and a "
              "disagreeing read.")
        if none_count:
            print(f"({none_count}/{args.readings} reads found nothing marked "
                  "at all -- pattern 4 from the P-spec.)")

    print(f"\nFrames + raw per-line colour log saved to {out_dir}")


if __name__ == "__main__":
    main()
