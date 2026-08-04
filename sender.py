"""Delivery of OCR results downstream.

Destination (DB / dashboard / webhook / the future AI model endpoint) isn't
decided yet, so this defaults to writing JSON to a local queue folder.
Swap `send_result` internals for a `requests.post(...)` call once the
Lemonade/FastFlowLM ingestion endpoint is defined — callers don't need to change.
"""
import json
import os

OUTPUT_DIR = "captures"


def send_result(result, image=None, tag=None):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stamp = result.get("captured_at") or "unknown-time"
    name = f"{stamp}_{tag}" if tag else stamp
    json_path = os.path.join(OUTPUT_DIR, f"{name}.json")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    if image is not None:
        import cv2
        cv2.imwrite(os.path.join(OUTPUT_DIR, f"{name}.png"), image)

    print(f"[sender] wrote {json_path}")
    return json_path
