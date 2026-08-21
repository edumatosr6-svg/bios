"""Prototype CLI: capture a BIOS screen image and OCR it into structured JSON
(text + per-word/line bounding boxes), ready to later feed an AI model.

Usage:
    python main.py --source file --input test_images/bios1.jpg --output out.json
    python main.py --source camera --camera-source 0 --output out.json
    python main.py --source camera --camera-source http://192.168.0.3:8080/video --output out.json
"""
import argparse
import json
import sys

from capture import capture_from_camera, load_from_file
from extract import DEFAULT_HOST, DEFAULT_MODEL, DEFAULT_PORT, ExtractionError, extract_fields
from ocr import DEFAULT_ENGINE, ENGINE_CHOICES, create_ocr_engine
from selection import annotate_selection


def parse_args():
    parser = argparse.ArgumentParser(description="Capture + OCR a BIOS screen")
    parser.add_argument("--source", choices=["camera", "file"], required=True)
    parser.add_argument("--input", help="Image path (required when --source file)")
    parser.add_argument("--camera-source", default="0",
                         help="Webcam index (e.g. 0) or a stream URL (e.g. http://<ip>:8080/video)")
    parser.add_argument("--output", help="Path to write JSON result (default: stdout)")
    parser.add_argument("--engine", choices=ENGINE_CHOICES, default=DEFAULT_ENGINE)
    parser.add_argument("--lang", default=None, help="Language code (engine-specific default if omitted)")
    parser.add_argument("--upscale", type=float, default=2.0, help="Tesseract-only preprocessing upscale")
    parser.add_argument("--extract-fields", action="store_true",
                         help="Also run OCR text through the local LLM (Lemonade/FastFlowLM) to extract label->value fields")
    parser.add_argument("--perception", action="store_true",
                         help="Use the perception engine (perception/) instead of the "
                              "OCR + selection.py path. Off by default here so existing "
                              "automation keeps today's output shape; gui.py runs the "
                              "engine by default and uses --legacy as the opposite switch.")
    parser.add_argument("--narrate", action="store_true",
                         help="Requires --perception. Send the digest contract to the "
                              "local LLM and save its free-text description of what it "
                              "understood under a 'cognition' key. Exploratory: the "
                              "answer is kept as-is for a human to judge, unchecked.")
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


def main():
    args = parse_args()

    if args.source == "file":
        if not args.input:
            print("--input is required when --source file", file=sys.stderr)
            sys.exit(1)
        image = load_from_file(args.input)
    else:
        image = capture_from_camera(camera_source=args.camera_source)

    if args.perception:
        # Single shot, so the high-level wrapper is fine -- there is no
        # loop to amortise the OCR model load across (watcher.py builds
        # the stages itself for exactly that reason). Note --upscale and
        # --lang are legacy/Tesseract options and have no effect here.
        from perception import perceive

        perceived = perceive(frames=[image], engine=args.engine, view="both")
        result = dict(perceived.contract["full"])

        if args.narrate:
            from cognition import fact_summary, narrate_contract

            fact_check = fact_summary(perceived.contract["full"])
            try:
                result["cognition"] = {
                    "narration": narrate_contract(
                        perceived.contract, host=args.llm_host,
                        port=args.llm_port, model=args.llm_model,
                    ),
                    "error": None,
                    "fact_check": fact_check,
                }
            except ExtractionError as e:
                print(f"[main] narration failed, keeping the contract only: {e}", file=sys.stderr)
                result["cognition"] = {"narration": None, "error": str(e), "fact_check": fact_check}
    else:
        engine = create_ocr_engine(args.engine, lang=args.lang, upscale=args.upscale)
        result = engine.read(image)
        result["screen_bg_color"] = annotate_selection(image, result["blocks"])

        if args.extract_fields:
            try:
                fields, unverified = extract_fields(
                    result, host=args.llm_host, port=args.llm_port, model=args.llm_model
                )
                result["fields"] = fields
                result["fields_unverified"] = unverified
            except ExtractionError as e:
                print(f"[main] field extraction failed, keeping raw OCR only: {e}", file=sys.stderr)
                result["fields"] = None
                result["fields_unverified"] = None
                result["fields_error"] = str(e)

    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"Wrote {args.output}")
    else:
        print(payload)


if __name__ == "__main__":
    main()
