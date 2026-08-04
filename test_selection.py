"""Scores selection/highlight detection against known ground truth.

Three sources, deliberately covering both ways a BIOS marks selection:

* Synthetic screenshots from make_test_image.py -- selection drawn as an
  inverted background bar. Ground truth known by construction.
* Real camera captures of an AMI BIOS (REAL_CASES) -- selection marked by
  TEXT colour instead (the selected entry is white while every other menu
  entry is blue), with the background unchanged. Ground truth read off
  the photos by eye.
* Every other saved capture -- none contain a BIOS selection, so anything
  flagged there is a false positive.

Reusing the stored OCR bboxes from the JSON sidecars keeps the capture
sweep fast enough to iterate on -- no need to re-run OCR.

Run: py -3.13 test_selection.py
"""
import glob
import json
import os
import sys

import cv2

from make_test_image import TEST_CASES
from selection import annotate_selection

# Expected `region` for each synthetic highlight, known by construction
# (menu items are drawn in the horizontal tab row; settings rows are body).
SYNTHETIC_REGIONS = {"Main": "menu_strip", "CPU Type": "body", "AMD Ryzen AI MAX 395": "body"}

# Real AMI BIOS photos. 20260803-154341 shows both levels at once: "Advanced"
# is the active top-level tab (menu_strip), "ACPI Configuration" is the
# focused item within it (body) -- see ESTUDO_SELECAO.md for why both are
# reported. The other two photos are framed without the tab row visible.
# Matched by prefix because OCR spelling varies between shots.
REAL_CASES = {
    "captures/20260803-154341_auto": {"Advanced": "menu_strip", "ACPI": "body"},
    "captures/20260803-154327_auto": {"ACPI": "body"},
    "captures/20260803-154414_auto": {"ACPI": "body"},
}


def _lines(blocks):
    return [line for block in blocks for line in block["lines"]]


def score_synthetic():
    from ocr import create_ocr_engine

    engine = create_ocr_engine("paddleocr")
    all_ok = True

    for name, expected in TEST_CASES.items():
        if not os.path.exists(name):
            print(f"  {name}: MISSING -- run: py -3.13 make_test_image.py")
            all_ok = False
            continue

        image = cv2.imread(name)
        result = engine.read(image)
        annotate_selection(image, result["blocks"])
        hit_lines = [line for line in _lines(result["blocks"]) if line["highlighted"]]
        flagged = {line["text"] for line in hit_lines}

        missed = expected - flagged
        extra = flagged - expected
        wrong_region = [
            line["text"] for line in hit_lines
            if line["text"] in SYNTHETIC_REGIONS
            and line["region"] != SYNTHETIC_REGIONS[line["text"]]
        ]
        ok = not missed and not extra and not wrong_region
        all_ok = all_ok and ok
        print(f"  {name}: {'OK' if ok else 'FAIL'} "
              f"flagged={sorted(flagged)} expected={sorted(expected)}"
              + (f" missed={sorted(missed)}" if missed else "")
              + (f" extra={sorted(extra)}" if extra else "")
              + (f" wrong_region={wrong_region}" if wrong_region else ""))

    return all_ok


def score_real():
    """Real BIOS photos: every expected (prefix, region) pair must be
    flagged, in the right region, and nothing else flagged.
    """
    all_ok = True
    for name, expected in REAL_CASES.items():
        blocks = json.load(open(name + ".json", encoding="utf-8"))["blocks"]
        image = cv2.imread(name + ".png")
        annotate_selection(image, blocks)
        hit_lines = [line for line in _lines(blocks) if line["highlighted"]]

        matched_prefixes = set()
        wrong = []
        for line in hit_lines:
            prefix = next((p for p in expected if line["text"].startswith(p)), None)
            if prefix and expected[prefix] == line["region"]:
                matched_prefixes.add(prefix)
            else:
                wrong.append((line["text"], line["region"]))

        ok = matched_prefixes == set(expected) and not wrong
        all_ok = all_ok and ok
        print(f"  {os.path.basename(name)}: {'OK' if ok else 'FAIL'} "
              f"flagged={[(l['text'], l['region']) for l in hit_lines]} expected={expected}")
    return all_ok


def score_captures():
    total_lines = 0
    total_flagged = 0
    offenders = []

    for json_path in sorted(glob.glob("captures/*.json")):
        png_path = json_path[:-5] + ".png"
        if not os.path.exists(png_path):
            continue
        if png_path[:-4] in REAL_CASES:  # scored above, has a real selection
            continue
        with open(json_path, encoding="utf-8") as f:
            blocks = json.load(f).get("blocks")
        if not blocks:
            continue
        image = cv2.imread(png_path)
        if image is None:
            continue

        annotate_selection(image, blocks)
        lines = _lines(blocks)
        flagged = [line for line in lines if line["highlighted"]]
        total_lines += len(lines)
        total_flagged += len(flagged)
        if flagged:
            offenders.append((os.path.basename(png_path), len(flagged), len(lines),
                               [line["text"][:40] for line in flagged]))

    rate = 100 * total_flagged / max(1, total_lines)
    print(f"  {total_flagged}/{total_lines} lines flagged ({rate:.1f}%) "
          f"across {len(glob.glob('captures/*.png'))} captures")
    for name, n_flagged, n_lines, texts in offenders[:10]:
        print(f"    {name}: {n_flagged}/{n_lines} {texts}")
    if len(offenders) > 10:
        print(f"    ... and {len(offenders) - 10} more images with flags")
    return rate


if __name__ == "__main__":
    print("Synthetic cases -- inverted background bar (exact match required):")
    synthetic_ok = score_synthetic()
    print("\nReal BIOS photos -- selection by text colour (exact match required):")
    real_ok = score_real()
    print("\nOther captures (no genuine selections -- flags here are false positives):")
    false_positive_rate = score_captures()

    print()
    if synthetic_ok and real_ok and false_positive_rate < 2.0:
        print("PASS")
        sys.exit(0)
    print(f"FAIL (synthetic_ok={synthetic_ok}, real_ok={real_ok}, "
          f"false_positive_rate={false_positive_rate:.1f}%)")
    sys.exit(1)
