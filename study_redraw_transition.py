"""Does the BIOS redraw the sidebar in stages, with a mid-redraw instant
that has no colour signal at all?

The compression study (`study_jpeg_compression_sensitivity.py`) confirmed
one mechanism that can produce pattern 4 (nothing detected) -- but ruled
out the obvious compression *source* (MJPG) for the camera actually in
use here. The other standing hypothesis in `docs/specs/p-specs/deteccao-
cursor-barra-lateral-instavel-entre-frames.md` is capture timing: a frame
grabbed mid-redraw might show text before the highlight colour catches up
(or vice versa). `BiosSession.read_cursor()` always waits for
`wait_stable()` first, so it never actually looks at that window -- this
script deliberately does, by grabbing raw frames as fast as the camera
will deliver them right after a keypress, with no settle wait at all.

Needs the cable (one keypress: `down`, inside the sidebar -- safe, just
moves the cursor, never presses Enter). Point the camera at the sidebar
first with a known state.

Run: py -3.13 study_redraw_transition.py --serial-port COM3
"""
import argparse
import json
import os
import time

import cv2

from biostools.screen import legacy_cursor
from biostools.session import BiosSession
from ocr import DEFAULT_ENGINE, ENGINE_CHOICES
from selection import annotate_selection


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--camera-source", default="0")
    parser.add_argument("--engine", choices=ENGINE_CHOICES, default=DEFAULT_ENGINE)
    parser.add_argument("--resolution", default="1280x720")
    parser.add_argument("--serial-port", required=True)
    parser.add_argument("--focus-first", action="store_true",
                        help="Press 'left' before the timed key, to make sure "
                             "focus is already in the sidebar")
    parser.add_argument("--key", default="down",
                        help="Key to press right before the rapid-grab burst")
    parser.add_argument("--frames", type=int, default=25,
                        help="How many raw frames to grab back-to-back, as "
                             "fast as the camera delivers them")
    parser.add_argument("--out-dir", default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    resolution = tuple(int(v) for v in args.resolution.lower().split("x"))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or os.path.join("captures", f"redraw_transition_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    with BiosSession(camera_source=args.camera_source, engine=args.engine,
                      resolution=resolution,
                      serial_port=args.serial_port) as session:
        if args.focus_first:
            session.press("left")
            time.sleep(0.3)
            print("pressed 'left' to focus the sidebar, then paused 0.3s")

        print(f"pressing {args.key!r}, then grabbing {args.frames} raw frames "
              f"as fast as possible (no settle wait)...")
        t_press = time.monotonic()
        session.press(args.key)

        raw = []
        for _ in range(args.frames):
            ok, frame = session.cap.read()
            t = time.monotonic() - t_press
            if ok:
                raw.append((t, frame))

        print(f"grabbed {len(raw)} frames spanning "
              f"{raw[-1][0] - raw[0][0]:.3f}s after the keypress\n")

        engine_obj = session._legacy_engine()
        log = []
        for i, (t, frame) in enumerate(raw):
            result = engine_obj.read(frame)
            result["screen_bg_color"] = annotate_selection(frame, result["blocks"])
            marked = legacy_cursor(result)
            text = marked["text"] if marked else None
            log.append({"index": i, "t": round(t, 4), "marked": text})
            cv2.imwrite(os.path.join(out_dir, f"{i:03d}_t{t:+.3f}.png"), frame)
            print(f"[{i:03d}] t={t:+.3f}s  marked={text!r}")

    with open(os.path.join(out_dir, "transition_log.json"), "w",
              encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    texts = [entry["marked"] for entry in log]
    distinct = sorted(set(texts), key=lambda v: (v is None, v))
    print(f"\n{len(distinct)} distinct marked value(s) across the burst: {distinct}")
    if None in texts and any(t is not None for t in texts):
        first_none = next(e["t"] for e in log if e["marked"] is None)
        print(f"\nFOUND a transient gap: signal present, then briefly None at "
              f"t={first_none:+.3f}s, matching what pattern 4 looks like -- this "
              "would confirm redraw timing as a real, separate mechanism from "
              "the compression one already confirmed. Inspect the frames in "
              f"{out_dir} around that timestamp.")
    elif texts.count(None) == len(texts):
        print("\nEvery frame in the burst was already ambiguous/undetermined -- "
              "inconclusive for the timing hypothesis specifically (may just be "
              "pattern 3, not a transition artifact). Try from a starting state "
              "with a clean single signal.")
    else:
        print("\nNo transient gap seen in this burst -- no support for redraw "
              "timing this time. Try again, or with a longer burst / higher "
              "camera frame rate if the window is narrower than what was "
              "sampled here.")

    print(f"\nFrames + log saved to {out_dir}")


if __name__ == "__main__":
    main()
