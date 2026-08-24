"""Can JPEG compression alone turn a clean, real signal into pattern 4
(nothing detected)?

Found by accident 2026-08-24: building a test fixture, a `selection.py`
verdict flipped (abstain -> decide alone) purely because a frame had been
saved to JPG and reread, not because anything about the real BIOS state
changed (see `docs/specs/p-specs/deteccao-cursor-barra-lateral-instavel-
entre-frames.md`). That was one data point at one quality level (OpenCV's
default, ~95). This asks the sharper question directly: take a frame with
a KNOWN, unambiguous highlight, and turn the compression dial down --
does the detector's confidence erode gracefully, or does it fall off a
cliff into "nothing marked" the way pattern 4 looks live?

No hardware needed -- this only touches a saved frame in memory (never
written back to disk), re-encoding it at each quality level with
`cv2.imencode`/`imdecode` and re-running the exact same OCR + selection.py
pipeline `BiosSession.read_cursor()` uses.

Run: py -3.13 study_jpeg_compression_sensitivity.py
"""
import cv2
import numpy as np

from biostools.screen import legacy_cursor, normalize
from ocr import DEFAULT_ENGINE, create_ocr_engine
from selection import annotate_selection

FRAME_PATH = "captures/positivo_sidebar_pattern1_advanced.jpg"
EXPECTED_ENTRY = "advanced"
QUALITIES = [95, 90, 80, 70, 60, 50, 40, 30, 20, 10]


def recompress(frame, quality):
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return cv2.imdecode(np.frombuffer(buf.tobytes(), np.uint8), cv2.IMREAD_COLOR)


def read_cursor(frame, engine):
    result = engine.read(frame)
    result["screen_bg_color"] = annotate_selection(frame, result["blocks"])
    return result


def main():
    frame = cv2.imread(FRAME_PATH)
    if frame is None:
        raise SystemExit(f"fixture ausente: {FRAME_PATH}")
    engine = create_ocr_engine(DEFAULT_ENGINE)

    print(f"source: {FRAME_PATH}  expected marked entry: {EXPECTED_ENTRY!r}\n")

    baseline = read_cursor(frame, engine)
    marked = legacy_cursor(baseline)
    print(f"[raw, uncompressed]  marked={marked['text'] if marked else None!r}")
    if marked:
        print(f"    fg={marked.get('fg_color')} bg={marked.get('bg_color')}")

    broke_at = None
    for q in QUALITIES:
        compressed = recompress(frame, q)
        reading = read_cursor(compressed, engine)
        marked = legacy_cursor(reading)
        text = marked["text"] if marked else None
        matches = marked is not None and normalize(text) == EXPECTED_ENTRY
        status = "ok" if matches else ("WRONG" if marked else "NOTHING DETECTED")
        print(f"[quality={q:3d}]  marked={text!r}  ({status})")
        if marked:
            print(f"    fg={marked.get('fg_color')} bg={marked.get('bg_color')}")
        if not matches and broke_at is None:
            broke_at = q

    print()
    if broke_at is None:
        print("STABLE across all tested quality levels -- compression alone did "
              "not reproduce pattern 4 on this frame. The margin here is wide; "
              "try a frame closer to the detection threshold if this matters.")
    else:
        print(f"BROKE at quality={broke_at}: compression alone was enough to "
              "lose or corrupt the signal. This supports the compression "
              "hypothesis as a real mechanism, alongside (not necessarily "
              "instead of) the capture-timing hypothesis in the P-spec.")


if __name__ == "__main__":
    main()
