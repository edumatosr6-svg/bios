"""Method 5: spot the selection by watching it MOVE.

The other four methods judge a single photo and must infer, from colour
alone, which entry looks special. But the factory camera watches a live
screen: when an operator presses a key the highlight jumps from one row
to another, and the only parts of the picture that change are the row it
left and the row it landed on. Differencing two settled frames therefore
points straight at the selection without knowing anything about the BIOS
palette, its polarity, or whether it draws a bar at all.

Two frames give two candidate rows (departed and arrived). Deciding which
is current needs one extra bit of evidence, so a single-frame method acts
as the tie-breaker over just those two candidates -- a far easier job than
picking one row out of twenty.

Run: py -3.13 study_temporal.py
"""
import cv2
import numpy as np

from make_test_image import ROWS, build
from ocr import create_ocr_engine
from selection import _color_distance, _foreground_color, _perimeter_pixels
from study_selection_methods import RING, _geometry

MIN_CHANGED_FRACTION = 0.15  # of a line's pixels, before it counts as changed
PIXEL_CHANGE_THRESHOLD = 30  # per-pixel intensity delta that counts as change


def changed_lines(previous, current, blocks):
    """Lines whose pixels differ between two settled frames."""
    previous_gray = cv2.cvtColor(previous, cv2.COLOR_BGR2GRAY)
    current_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
    delta = cv2.absdiff(previous_gray, current_gray) > PIXEL_CHANGE_THRESHOLD

    changed = []
    for line, x0, y0, x1, y1 in _geometry(current, blocks):
        region = delta[y0:y1, x0:x1]
        if region.size and region.mean() >= MIN_CHANGED_FRACTION:
            changed.append(line)
    return changed


def _looks_highlighted(image, line):
    """Tie-break score: how far this line's own colours sit from the rest
    of the screen. Only ever compared between the handful of changed
    lines, so it doesn't need to be reliable screen-wide.
    """
    bb = line["bbox"]
    height, width = image.shape[:2]
    x0, y0 = max(0, bb["left"]), max(0, bb["top"])
    x1 = min(width, bb["left"] + bb["width"])
    y1 = min(height, bb["top"] + bb["height"])
    if x1 - x0 < 2 * RING or y1 - y0 < 2 * RING:
        return -1.0

    crop = image[y0:y1, x0:x1]
    background = np.median(_perimeter_pixels(crop), axis=0)
    foreground = _foreground_color(crop, background)
    screen_bg = np.median(image.reshape(-1, 3), axis=0)
    return _color_distance(background, screen_bg) + 0.5 * _color_distance(
        foreground, screen_bg)


def detect_by_movement(previous, current, blocks):
    """Selection in `current`, inferred from what moved since `previous`."""
    candidates = changed_lines(previous, current, blocks)
    if not candidates:
        return set()
    best = max(candidates, key=lambda line: _looks_highlighted(current, line))
    return {best["text"]}


def _simulate_camera(image, noise_sigma, shift_px, brightness_shift, rng):
    """Approximate what a handheld camera does to two shots of the same
    screen: sensor noise, a pixel or two of movement, and a small exposure
    drift. Clean synthetic frames would flatter this method unfairly.
    """
    result = image.astype(np.float32)
    if shift_px:
        matrix = np.float32([[1, 0, rng.integers(-shift_px, shift_px + 1)],
                             [0, 1, rng.integers(-shift_px, shift_px + 1)]])
        result = cv2.warpAffine(result, matrix, (image.shape[1], image.shape[0]),
                                borderMode=cv2.BORDER_REPLICATE)
    if brightness_shift:
        result += rng.uniform(-brightness_shift, brightness_shift)
    if noise_sigma:
        result += rng.normal(0, noise_sigma, result.shape)
    return np.clip(result, 0, 255).astype(np.uint8)


def _run_sequence(engine, conditions, rng):
    frames = [cv2.cvtColor(np.array(build(theme="dark", highlight_menu=None,
                                          highlight_row=row)), cv2.COLOR_RGB2BGR)
              for row in range(len(ROWS))]

    correct = 0
    for index in range(1, len(frames)):
        previous = _simulate_camera(frames[index - 1], *conditions, rng)
        current = _simulate_camera(frames[index], *conditions, rng)
        blocks = engine.read(current)["blocks"]
        detected = detect_by_movement(previous, current, blocks)
        expected = ROWS[index][0]
        correct += any(t.startswith(expected.split()[0]) for t in detected)
    return correct, len(frames) - 1


def main():
    engine = create_ocr_engine("paddleocr")
    rng = np.random.default_rng(0)

    #        label                       noise  shift  brightness
    scenarios = [
        ("ideal (synthetic, no noise)",    0.0,     0,        0.0),
        ("light sensor noise",             4.0,     0,        2.0),
        ("noise + 1px handshake",          4.0,     1,        2.0),
        ("noise + 2px handshake",          6.0,     2,        4.0),
        ("noise + 4px handshake",          8.0,     4,        6.0),
    ]

    print("Selection stepping through the settings rows, one frame per position "
          "--\nwhat the camera sees while an operator arrows through the menu.\n")
    print(f"{'conditions':32} {'correct'}")
    print("-" * 46)
    for label, *conditions in scenarios:
        correct, total = _run_sequence(engine, conditions, rng)
        print(f"{label:32} {correct}/{total}")

    print("\nMovement is the strongest single cue when frames line up, and the "
          "first\nthing to degrade when they don't -- so a real deployment wants "
          "frame\nalignment (or a fixed, rigidly mounted camera) before leaning "
          "on it.")


if __name__ == "__main__":
    main()
