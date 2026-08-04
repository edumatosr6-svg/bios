"""Comparative study: how can a program tell which menu entry is selected?

Each method below perceives selection through a different principle, and
all are scored against the same ground truth so the choice is made by
measurement rather than argument. Run:

    py -3.13 study_selection_methods.py

Ground truth (same three sets test_selection.py uses):
  * synthetic screens where selection is an inverted background bar
  * real AMI BIOS photos where selection is a different TEXT colour
  * ~240 captures with no selection at all (any flag = false positive)

Methods:
  1 colour-stats   what selection.py ships: background inversion, plus a
                   text-colour outlier judged against the other lines' spread
  2 luminance-flip is the text lighter-than or darker-than its background,
                   and does this line disagree with the majority? Ignores hue
                   entirely, so it should survive a palette it has never seen
  3 row-band       compare whole horizontal strips across the screen rather
                   than tight text boxes -- a selection bar usually runs wider
                   than the words sitting on it
  4 geometric-fill look for a solid filled rectangle behind the text (shape
                   detection), rather than reasoning about colour statistics

A fifth approach, temporal differencing, needs consecutive frames rather
than one image, so it is studied separately in study_temporal.py.
"""
import glob
import json
import os
import sys

import cv2
import numpy as np

from make_test_image import TEST_CASES
from selection import (MAD_MULTIPLIER, MAX_PERIMETER_STD, MAX_TEXT_COLOR_OUTLIERS,
                       MIN_BG_DISTANCE, MIN_FG_DISTANCE, MIN_LINES_FOR_FG_REF,
                       RING, _color_distance, _foreground_color, _perimeter_pixels)

REAL_CASES = {
    "captures/20260803-154341_auto": "ACPI",
    "captures/20260803-154327_auto": "ACPI",
    "captures/20260803-154414_auto": "ACPI",
}
LUMA = np.array([0.114, 0.587, 0.299])  # BGR


def _geometry(image, blocks):
    """Per-line bbox clipped to the frame, skipping degenerate boxes."""
    height, width = image.shape[:2]
    for block in blocks:
        for line in block["lines"]:
            bb = line["bbox"]
            x0, y0 = max(0, bb["left"]), max(0, bb["top"])
            x1 = min(width, bb["left"] + bb["width"])
            y1 = min(height, bb["top"] + bb["height"])
            if x1 - x0 >= 2 * RING and y1 - y0 >= 2 * RING:
                yield line, x0, y0, x1, y1


def _bg_fg(image, x0, y0, x1, y1):
    crop = image[y0:y1, x0:x1]
    ring = _perimeter_pixels(crop)
    bg = np.median(ring, axis=0)
    return bg, _foreground_color(crop, bg), float(ring.std(axis=0).mean())


# ---------------------------------------------------------------- method 1

def method_colour_stats(image, blocks):
    """Ships in selection.py. Two signals: an inverted background bar, or a
    text colour that stands outside the spread of the other lines' colours.
    """
    screen_bg = np.median(image.reshape(-1, 3), axis=0)
    measured = [(line, *_bg_fg(image, x0, y0, x1, y1))
                for line, x0, y0, x1, y1 in _geometry(image, blocks)]
    if not measured:
        return set()

    typical_fg = cutoff = None
    if len(measured) >= MIN_LINES_FOR_FG_REF:
        fgs = np.array([fg for _, _, fg, _ in measured])
        typical_fg = np.median(fgs, axis=0)
        dists = np.array([_color_distance(fg, typical_fg) for fg in fgs])
        med = float(np.median(dists))
        mad = float(np.median(np.abs(dists - med)))
        cutoff = max(MIN_FG_DISTANCE, med + MAD_MULTIPLIER * max(mad, 1.0))

    hits, outliers = set(), []
    for line, bg, fg, std in measured:
        d_bg = _color_distance(bg, screen_bg)
        if (d_bg > MIN_BG_DISTANCE and std <= MAX_PERIMETER_STD
                and _color_distance(fg, screen_bg) < d_bg):
            hits.add(line["text"])
        elif typical_fg is not None and _color_distance(fg, typical_fg) > cutoff:
            outliers.append(line["text"])
    if len(outliers) <= MAX_TEXT_COLOR_OUTLIERS:
        hits.update(outliers)
    return hits


# ---------------------------------------------------------------- method 2

MIN_LUMA_CONTRAST = 25.0


def method_luminance_flip(image, blocks):
    """Selection as a contrast-direction flip: most lines share a polarity
    (light text on dark, or dark on light) and the selected one disagrees.
    Hue plays no part, so an unfamiliar colour scheme shouldn't matter.
    """
    polarities, entries = [], []
    for line, x0, y0, x1, y1 in _geometry(image, blocks):
        bg, fg, _ = _bg_fg(image, x0, y0, x1, y1)
        polarity = float(fg @ LUMA - bg @ LUMA)
        entries.append((line, polarity))
        polarities.append(polarity)

    if len(entries) < MIN_LINES_FOR_FG_REF:
        return set()

    majority_sign = np.sign(np.median(polarities))
    if majority_sign == 0:
        return set()

    flipped = [line["text"] for line, polarity in entries
               if np.sign(polarity) != majority_sign
               and abs(polarity) > MIN_LUMA_CONTRAST]
    # Same reasoning as the colour-stats cap: a BIOS selects one entry, so a
    # screen where many lines disagree isn't showing a selection at all.
    return set(flipped) if len(flipped) <= MAX_TEXT_COLOR_OUTLIERS else set()


# ---------------------------------------------------------------- method 3

MIN_BAND_DISTANCE = 40.0


def method_row_band(image, blocks):
    """Compare full-width horizontal strips instead of tight text boxes. A
    selection bar typically extends past the words it sits behind, so the
    whole row shifts colour -- visible in a strip, easy to miss in a bbox.
    """
    entries = []
    for line, x0, y0, x1, y1 in _geometry(image, blocks):
        band = image[y0:y1, :]
        if band.size:
            entries.append((line, np.median(band.reshape(-1, 3), axis=0)))

    if len(entries) < MIN_LINES_FOR_FG_REF:
        return set()

    typical = np.median(np.array([c for _, c in entries]), axis=0)
    distances = np.array([_color_distance(c, typical) for _, c in entries])
    med = float(np.median(distances))
    mad = float(np.median(np.abs(distances - med)))
    cutoff = max(MIN_BAND_DISTANCE, med + MAD_MULTIPLIER * max(mad, 1.0))

    hits = [line["text"] for (line, _), d in zip(entries, distances) if d > cutoff]
    return set(hits) if len(hits) <= MAX_TEXT_COLOR_OUTLIERS else set()


# ---------------------------------------------------------------- method 4

FLATNESS_WINDOW = 9
MAX_FLAT_STD = 8.0
MIN_BAR_AREA_RATIO = 0.0015
MIN_BAR_ASPECT = 2.0


def _flat_regions(image):
    """Connected regions of near-uniform brightness -- candidate solid fills."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    mean = cv2.boxFilter(gray, -1, (FLATNESS_WINDOW, FLATNESS_WINDOW))
    mean_sq = cv2.boxFilter(gray * gray, -1, (FLATNESS_WINDOW, FLATNESS_WINDOW))
    std = np.sqrt(np.maximum(mean_sq - mean * mean, 0.0))
    flat = (std < MAX_FLAT_STD).astype(np.uint8)
    return cv2.connectedComponentsWithStats(flat, connectivity=8)


def method_geometric_fill(image, blocks):
    """Find the selection bar as a SHAPE: a wide, solid, rectangular fill
    whose colour isn't the page background, then report the lines sitting
    inside it. Says nothing about selections drawn without a bar.
    """
    height, width = image.shape[:2]
    screen_bg = np.median(image.reshape(-1, 3), axis=0)
    count, labels, stats, _ = _flat_regions(image)
    min_area = MIN_BAR_AREA_RATIO * height * width

    bars = []
    for label in range(1, count):
        x, y, w, h, area = stats[label]
        if area < min_area or h == 0 or w / h < MIN_BAR_ASPECT:
            continue
        if area < 0.5 * w * h:  # must actually fill its bounding rectangle
            continue
        region_color = np.median(image[y:y + h, x:x + w].reshape(-1, 3), axis=0)
        if _color_distance(region_color, screen_bg) > MIN_BAND_DISTANCE:
            bars.append((x, y, w, h))

    hits = set()
    for line, x0, y0, x1, y1 in _geometry(image, blocks):
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        for bx, by, bw, bh in bars:
            if bx <= cx <= bx + bw and by <= cy <= by + bh:
                hits.add(line["text"])
                break
    return hits


METHODS = {
    "1 colour-stats (current)": method_colour_stats,
    "2 luminance-flip": method_luminance_flip,
    "3 row-band": method_row_band,
    "4 geometric-fill": method_geometric_fill,
}


def _load_ground_truth():
    from ocr import create_ocr_engine

    engine = create_ocr_engine("paddleocr")
    synthetic = []
    for name, expected in TEST_CASES.items():
        image = cv2.imread(name)
        synthetic.append((name, image, engine.read(image)["blocks"], expected))

    real = []
    for name, prefix in REAL_CASES.items():
        image = cv2.imread(name + ".png")
        blocks = json.load(open(name + ".json", encoding="utf-8"))["blocks"]
        real.append((name, image, blocks, prefix))

    negatives = []
    for json_path in sorted(glob.glob("captures/*.json")):
        png_path = json_path[:-5] + ".png"
        if not os.path.exists(png_path) or png_path[:-4] in REAL_CASES:
            continue
        blocks = json.load(open(json_path, encoding="utf-8")).get("blocks")
        image = cv2.imread(png_path) if blocks else None
        if image is not None:
            negatives.append((os.path.basename(png_path), image, blocks))
    return synthetic, real, negatives


def main():
    synthetic, real, negatives = _load_ground_truth()
    print(f"ground truth: {len(synthetic)} synthetic, {len(real)} real BIOS, "
          f"{len(negatives)} negative captures\n")

    header = f"{'method':26} {'synthetic bar':>14} {'real text-colour':>17} {'false positives':>17}"
    print(header)
    print("-" * len(header))

    results = {}
    for label, method in METHODS.items():
        synth_ok = sum(method(image, blocks) == expected
                       for _, image, blocks, expected in synthetic)

        real_ok = 0
        for _, image, blocks, prefix in real:
            hits = method(image, blocks)
            if hits and all(t.startswith(prefix) for t in hits):
                real_ok += 1

        total = flagged = 0
        for _, image, blocks in negatives:
            total += sum(len(b["lines"]) for b in blocks)
            flagged += len(method(image, blocks))
        rate = 100 * flagged / max(1, total)
        results[label] = (synth_ok, real_ok, rate)
        print(f"{label:26} {synth_ok}/{len(synthetic):<12} {real_ok}/{len(real):<15} "
              f"{flagged:4}/{total} ({rate:.2f}%)")

    return results


if __name__ == "__main__":
    main()
