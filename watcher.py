"""Fully automatic capture loop: watches the camera feed, detects when the
screen has stopped changing (a stable BIOS menu, as opposed to a boot
splash still animating or a blank/transitioning screen), and when it
does, automatically runs OCR and sends the result. No human ever takes
or forwards a photo -- the camera feed is read continuously by this process.

Debounce: once a stable screen is processed, it will not be reprocessed
until the screen changes away and stabilizes again (so leaving the
camera pointed at the same BIOS screen doesn't produce duplicate sends).
"""
import argparse
import signal
import sys
import time

import cv2

from capture import resolve_camera_source
from extract import DEFAULT_HOST, DEFAULT_MODEL, DEFAULT_PORT, ExtractionError, extract_fields
from ocr import DEFAULT_ENGINE, ENGINE_CHOICES, create_ocr_engine
from selection import annotate_selection
from sender import send_result


def frame_diff_score(prev_gray, curr_gray):
    return float(cv2.absdiff(prev_gray, curr_gray).mean())


def watch(
    camera_source=0,
    stable_threshold=1.5,
    stable_frames_required=8,
    poll_interval=0.3,
    change_threshold=8.0,
    engine=DEFAULT_ENGINE,
    lang=None,
    extract=False,
    perception=False,
    narrate=False,
    llm_host=DEFAULT_HOST,
    llm_port=DEFAULT_PORT,
    llm_model=DEFAULT_MODEL,
):
    """
    stable_threshold: max mean pixel diff between consecutive frames to
        still count as "not changing".
    stable_frames_required: how many consecutive stable frames before a
        screen is considered settled enough to OCR.
    change_threshold: how different the current stable screen must be
        from the last one we processed before we're willing to process
        it again (prevents re-sending the same static screen forever).
    """
    camera_source = resolve_camera_source(camera_source)
    cap = cv2.VideoCapture(camera_source)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera source {camera_source}")

    # SIGTERM (e.g. from `kill`, or a service manager stopping this process)
    # does not run Python's `finally` blocks by default, which leaves the
    # camera device locked open at the OS level -- the next start then fails
    # or hangs for a long time trying to reacquire it. Handle it explicitly.
    def _graceful_exit(signum, frame):
        cap.release()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _graceful_exit)
    signal.signal(signal.SIGINT, _graceful_exit)

    if perception:
        # Build the stages once, outside the loop. The high-level
        # perception.perceive() wrapper rebuilds Extraction on every call,
        # which reloads the OCR model -- fine for a single shot (main.py),
        # unacceptable in a loop that runs indefinitely.
        from perception.pipeline import run_pipeline
        from perception.stages import (
            Acquisition, Characterisation, Conditioning, Equivalence, Extraction,
            Grouping, Identity, Regionalisation, Serialisation, StateInference,
            Typing,
        )

        warm = [
            Conditioning(),
            Extraction(engine=engine),
            Characterisation(),
            Regionalisation(),
            Grouping(),
            Equivalence(),
            StateInference(),
            Typing(),
            Identity(),
            Serialisation(view="both"),
        ]
    else:
        engine = create_ocr_engine(engine, lang=lang)

    prev_gray = None
    last_processed_gray = None
    stable_count = 0

    print("[watcher] running, waiting for a stable BIOS screen...")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("[watcher] frame read failed, retrying...")
                time.sleep(poll_interval)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            if prev_gray is not None:
                score = frame_diff_score(prev_gray, gray)
                stable_count = stable_count + 1 if score < stable_threshold else 0

                if stable_count >= stable_frames_required:
                    is_new_screen = (
                        last_processed_gray is None
                        or frame_diff_score(last_processed_gray, gray) > change_threshold
                    )
                    if is_new_screen:
                        captured_at = time.strftime("%Y%m%d-%H%M%S")
                        if perception:
                            print("[watcher] stable screen detected, running perception...")
                            perceived = run_pipeline(
                                [Acquisition(frames=[frame], captured_at=captured_at)] + warm
                            )
                            result = {"captured_at": captured_at,
                                      **perceived.contract["full"]}
                            if narrate:
                                from cognition import fact_summary, narrate_contract

                                fact_check = fact_summary(perceived.contract["full"])
                                print(f"[watcher] {fact_check}")
                                try:
                                    narration = narrate_contract(
                                        perceived.contract,
                                        host=llm_host, port=llm_port, model=llm_model,
                                    )
                                    print(f"[watcher] LLM description: {narration}")
                                    result["cognition"] = {
                                        "narration": narration, "error": None,
                                        "fact_check": fact_check,
                                    }
                                except ExtractionError as e:
                                    print(f"[watcher] narration failed, keeping the contract only: {e}")
                                    result["cognition"] = {
                                        "narration": None, "error": str(e),
                                        "fact_check": fact_check,
                                    }
                        else:
                            print("[watcher] stable screen detected, running OCR...")
                            result = engine.read(frame)
                            result["captured_at"] = captured_at
                            result["screen_bg_color"] = annotate_selection(frame, result["blocks"])
                            if extract:
                                try:
                                    fields, unverified = extract_fields(
                                        result, host=llm_host, port=llm_port, model=llm_model
                                    )
                                    result["fields"] = fields
                                    result["fields_unverified"] = unverified
                                except ExtractionError as e:
                                    print(f"[watcher] field extraction failed, keeping raw OCR only: {e}")
                                    result["fields"] = None
                                    result["fields_unverified"] = None
                                    result["fields_error"] = str(e)
                        send_result(result, image=frame)
                        last_processed_gray = gray.copy()
                    stable_count = 0

            prev_gray = gray
            time.sleep(poll_interval)
    finally:
        cap.release()


def parse_args():
    parser = argparse.ArgumentParser(description="Automatic BIOS screen watcher")
    parser.add_argument("--camera-source", default="0",
                         help="Webcam index (e.g. 0) or a stream URL (e.g. http://<ip>:8080/video)")
    parser.add_argument("--engine", choices=ENGINE_CHOICES, default=DEFAULT_ENGINE)
    parser.add_argument("--lang", default=None, help="Language code (engine-specific default if omitted)")
    parser.add_argument("--stable-threshold", type=float, default=1.5)
    parser.add_argument("--stable-frames", type=int, default=8)
    parser.add_argument("--poll-interval", type=float, default=0.3)
    parser.add_argument("--change-threshold", type=float, default=8.0)
    parser.add_argument("--extract-fields", action="store_true",
                         help="Also run OCR text through the local LLM (Lemonade/FastFlowLM) to extract label->value fields")
    parser.add_argument("--perception", action="store_true",
                         help="Use the perception engine (perception/) instead of the "
                              "OCR + selection.py path. Off by default here so existing "
                              "automation keeps today's output shape; gui.py runs the "
                              "engine by default and uses --legacy as the opposite switch.")
    parser.add_argument("--narrate", action="store_true",
                         help="Requires --perception. Send the digest contract to the "
                              "local LLM, print its free-text description of what it "
                              "understood, and save it under a 'cognition' key. "
                              "Exploratory: kept as-is for a human to judge, unchecked.")
    parser.add_argument("--llm-host", default=DEFAULT_HOST)
    parser.add_argument("--llm-port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--llm-model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    if args.narrate and not args.perception:
        parser.error(
            "--narrate requires --perception: cognition consumes the perception "
            "digest contract, which the legacy path never produces."
        )
    return args


if __name__ == "__main__":
    args = parse_args()
    watch(
        camera_source=args.camera_source,
        stable_threshold=args.stable_threshold,
        stable_frames_required=args.stable_frames,
        poll_interval=args.poll_interval,
        change_threshold=args.change_threshold,
        engine=args.engine,
        lang=args.lang,
        extract=args.extract_fields,
        perception=args.perception,
        narrate=args.narrate,
        llm_host=args.llm_host,
        llm_port=args.llm_port,
        llm_model=args.llm_model,
    )
