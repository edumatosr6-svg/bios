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
from ocr import create_ocr_engine
from selection import annotate_selection


def parse_args():
    parser = argparse.ArgumentParser(description="Capture + OCR a BIOS screen")
    parser.add_argument("--source", choices=["camera", "file"], required=True)
    parser.add_argument("--input", help="Image path (required when --source file)")
    parser.add_argument("--camera-source", default="0",
                         help="Webcam index (e.g. 0) or a stream URL (e.g. http://<ip>:8080/video)")
    parser.add_argument("--output", help="Path to write JSON result (default: stdout)")
    parser.add_argument("--engine", choices=["tesseract", "paddleocr"], default="paddleocr")
    parser.add_argument("--lang", default=None, help="Language code (engine-specific default if omitted)")
    parser.add_argument("--upscale", type=float, default=2.0, help="Tesseract-only preprocessing upscale")
    parser.add_argument("--extract-fields", action="store_true",
                         help="Also run OCR text through the local LLM (Lemonade/FastFlowLM) to extract label->value fields")
    parser.add_argument("--llm-host", default=DEFAULT_HOST)
    parser.add_argument("--llm-port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--llm-model", default=DEFAULT_MODEL)
    return parser.parse_args()


def main():
    args = parse_args()

    if args.source == "file":
        if not args.input:
            print("--input is required when --source file", file=sys.stderr)
            sys.exit(1)
        image = load_from_file(args.input)
    else:
        image = capture_from_camera(camera_source=args.camera_source)

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
