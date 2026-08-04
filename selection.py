"""Detect BIOS menu selection/highlight state from colour, not text.

OCR only reads characters, so it can't see which menu entry is currently
selected. This runs on the original colour frame, over the line-level
bounding boxes OCR already produced, and flags the selected line(s).

Real BIOSes mark selection in two different ways, and both are detected:

A. **Inverted background bar** -- a solid block of contrasting colour
   behind the entry (e.g. a white bar with black text on a black screen).

B. **Different text colour** -- background unchanged, but the selected
   entry's text switches colour (e.g. the AMI BIOS in captures/, where
   the selected entry is white while every other menu entry is blue).
   Signal A alone completely misses this.

Both signals are evaluated PER REGION, not against the whole screen. A
typical BIOS has (at least) two visually distinct regions: a top menu
strip (Main / Advanced / Boot / ...) and a body of settings rows, and
they routinely use different base colours. Comparing a menu-strip item
against the whole-screen colour makes every item in the strip look
"different" -- selected or not -- since the strip as a whole differs from
the body; only comparing it against its OWN strip-mates isolates which
one is actually selected. This was found the hard way: an early
region-unaware version detected the body selection correctly but
completely missed a real, visible tab-bar selection ("Advanced") and
came within one bad threshold of flagging the wrong tab instead.

Lines are grouped into regions with a single pass: cluster into rows by
vertical position, then any row of >= MIN_STRIP_SIZE lines is a "menu
strip" (compared against its own row-mates); everything else is "body"
(compared against the whole-screen colour, as before). This means a
single frame can now report highlights at both levels at once -- e.g. the
active top-level tab AND the focused item within it -- distinguished by
each line's `region` field ("menu_strip" or "body"). That is the answer
to "should the active tab be reported too": yes, as a same-shaped
highlight with a different `region`, not a separate concept.

Three measurement decisions matter more than the exact thresholds:

* Background is sampled from the bbox PERIMETER, not the whole crop. OCR
  bboxes hug the text tightly -- measured ink coverage of 51-73% on real
  captures -- so "most common colour in the crop" is frequently the glyph
  colour rather than the background. An early version made exactly that
  mistake and flagged 39.5% of all lines. The median over a border ring
  (glyphs concentrate in the interior) fixes it, and shrugs off the
  minority of ring pixels that do catch an ascender or descender.

* For the body region, signal B compares each line's text colour against
  the median text colour of the OTHER body lines, and requires it to
  stand out relative to how much those lines vary (median absolute
  deviation), not by a fixed distance. That adapts automatically to
  whatever palette a given BIOS uses -- which matters because the three
  target BIOS models are expected to differ.

* A menu strip is typically too small (4-7 items) for the body's
  MAD-based statistics to mean anything, and its floor
  (MIN_FG_DISTANCE=180, tuned against ~16-item body populations) rejected
  a real selection worth only 66.7 in a 5-item strip. Strips instead use
  a scale-free "runner-up" test: the most different item must clearly
  beat the SECOND most different item (`STRIP_RUNNER_UP_RATIO`), which
  needs no absolute-distance calibration at all. This part has thin
  validation -- exactly one real screen has a visible menu strip -- so
  treat `STRIP_*` constants as provisional until the other 2 BIOS models
  are available; test_selection.py must still pass after any retune.

Signal B (both body and strip) is capped at ONE outlier per region. A
BIOS selects one entry per region, so several odd-coloured lines in the
same region means it isn't showing a selection there at all.

Bold-weight detection is deliberately not attempted: without a
font-specific reference there's no reliable baseline to compare stroke
thickness against, so it would amount to guessing. Revisit if a real BIOS
turns out to mark selection by weight rather than colour.
"""
import numpy as np

# Body-region thresholds. Grid-searched against synthetic cases, 3 real
# AMI BIOS photos, and ~240 captures containing no selection at all.
# test_selection.py scores all three sets -- re-run it after any change.
MIN_BG_DISTANCE = 250.0        # signal A: line bg vs region bg
MAX_PERIMETER_STD = 34.0       # signal A: a selection bar is a flat fill
MIN_FG_DISTANCE = 180.0        # signal B (body): absolute floor before MAD applies
MAD_MULTIPLIER = 8.0           # signal B (body): how far outside the spread to require
MIN_LINES_FOR_FG_REF = 4       # too few lines and the median text colour is noise
MAX_TEXT_COLOR_OUTLIERS = 1    # signal B: a region selects one entry, not many
RING = 2                       # perimeter ring thickness, px

# Menu-strip (tab bar) region thresholds -- see docstring caveat above.
MIN_STRIP_SIZE = 4             # lines needed in a row before treating it as a strip
STRIP_OUTLIER_FLOOR = 60.0     # signal B (strip): minimum distance to even consider
STRIP_RUNNER_UP_RATIO = 2.2    # signal B (strip): winner must beat 2nd place by this much
ROW_GAP_FACTOR = 0.6           # row clustering: max vertical gap, x median line height


def _color_distance(a, b):
    return float(np.linalg.norm(np.asarray(a, dtype=float) - np.asarray(b, dtype=float)))


def _perimeter_pixels(crop, ring=RING):
    """Border ring of a crop. Glyph strokes concentrate in the interior,
    so this is background-dominated even for a tight text bbox.
    """
    h, w = crop.shape[:2]
    ring = max(1, min(ring, h // 2, w // 2))
    return np.vstack([
        crop[:ring, :].reshape(-1, 3),
        crop[-ring:, :].reshape(-1, 3),
        crop[:, :ring].reshape(-1, 3),
        crop[:, -ring:].reshape(-1, 3),
    ])


def _foreground_color(crop, background):
    """Mean colour of the pixels furthest from the background -- the ink."""
    flat = crop.reshape(-1, 3).astype(float)
    distances = np.linalg.norm(flat - np.asarray(background, dtype=float), axis=1)
    if not distances.size:
        return np.asarray(background, dtype=float)
    ink = flat[distances >= np.percentile(distances, 90)]
    if not ink.size:
        return np.asarray(background, dtype=float)
    return ink.mean(axis=0)


def _line_geometry(image, blocks):
    """All (line, x0, y0, x1, y1) with a usable (non-degenerate) crop."""
    height, width = image.shape[:2]
    out = []
    for block in blocks:
        for line in block["lines"]:
            bbox = line["bbox"]
            x0 = max(0, bbox["left"])
            y0 = max(0, bbox["top"])
            x1 = min(width, bbox["left"] + bbox["width"])
            y1 = min(height, bbox["top"] + bbox["height"])
            line["highlighted"] = False
            line["region"] = None
            line["bg_color"] = None
            line["fg_color"] = None
            if x1 - x0 >= 2 * RING and y1 - y0 >= 2 * RING:
                out.append((line, x0, y0, x1, y1))
    return out


def _measure(image, x0, y0, x1, y1):
    crop = image[y0:y1, x0:x1]
    ring = _perimeter_pixels(crop)
    bg = np.median(ring, axis=0)
    fg = _foreground_color(crop, bg)
    return bg, fg, float(ring.std(axis=0).mean())


def _cluster_rows(geometry):
    """1D clustering on each line's vertical centre: a new row starts when
    the gap to the previous centre exceeds ROW_GAP_FACTOR x the median
    line height on this screen.
    """
    if not geometry:
        return []
    heights = [y1 - y0 for _, _, y0, _, y1 in geometry]
    gap_threshold = ROW_GAP_FACTOR * float(np.median(heights))

    ordered = sorted(geometry, key=lambda e: (e[2] + e[4]) / 2)
    rows, current = [], [ordered[0]]
    prev_center = (ordered[0][2] + ordered[0][4]) / 2
    for entry in ordered[1:]:
        center = (entry[2] + entry[4]) / 2
        if center - prev_center > gap_threshold:
            rows.append(current)
            current = []
        current.append(entry)
        prev_center = center
    rows.append(current)
    return rows


def _apply_region(entries, image, region_name, bg_reference, fg_population,
                  min_fg_distance, min_population, use_runner_up):
    """Shared signal A + signal B logic for one region's lines, against
    that region's own reference colours (`bg_reference`/`fg_population`).
    """
    measured = [(line, x0, y0, x1, y1, *_measure(image, x0, y0, x1, y1))
                for line, x0, y0, x1, y1 in entries]
    for line, *_rest, bg, fg, _std in measured:
        line["bg_color"] = [int(c) for c in bg]
        line["fg_color"] = [int(c) for c in fg]

    bg_center = np.median(bg_reference, axis=0) if len(bg_reference) else None
    bar_hits = []
    for line, *_geom, bg, fg, std in measured:
        if bg_center is None:
            continue
        d_bg = _color_distance(bg, bg_center)
        if (d_bg > MIN_BG_DISTANCE and std <= MAX_PERIMETER_STD
                and _color_distance(fg, bg_center) < d_bg):
            bar_hits.append(line)

    for line in bar_hits:
        line["highlighted"] = True
        line["region"] = region_name
    if bar_hits or len(fg_population) < min_population:
        return

    typical_fg = np.median(fg_population, axis=0)
    ranked = sorted(
        ((_color_distance(fg, typical_fg), line) for line, *_g, bg, fg, _s in measured),
        key=lambda pair: pair[0],
    )

    if use_runner_up:
        winner_d, winner_line = ranked[-1]
        runner_up_d = ranked[-2][0] if len(ranked) >= 2 else 0.0
        if winner_d > STRIP_OUTLIER_FLOOR and winner_d > STRIP_RUNNER_UP_RATIO * max(runner_up_d, 1.0):
            winner_line["highlighted"] = True
            winner_line["region"] = region_name
    else:
        distances = np.array([d for d, _ in ranked])
        med = float(np.median(distances))
        mad = float(np.median(np.abs(distances - med)))
        cutoff = max(min_fg_distance, med + MAD_MULTIPLIER * max(mad, 1.0))
        outliers = [line for d, line in ranked if d > cutoff]
        if len(outliers) <= MAX_TEXT_COLOR_OUTLIERS:
            for line in outliers:
                line["highlighted"] = True
                line["region"] = region_name


def annotate_selection(image, blocks):
    """Mutates `blocks` in place: every line dict gains `highlighted`
    (bool), `region` ("menu_strip" | "body" | None), `bg_color`, `fg_color`
    (BGR, matching the input image). Returns the screen's overall
    background colour for reference. A single frame can report highlights
    in more than one region at once (e.g. an active tab AND a focused
    body item), since each is judged against its own region's colours.
    """
    screen_bg = np.median(image.reshape(-1, 3), axis=0)
    geometry = _line_geometry(image, blocks)
    rows = _cluster_rows(geometry)

    strip_rows = [row for row in rows if len(row) >= MIN_STRIP_SIZE]
    strip_ids = {id(entry) for row in strip_rows for entry in row}
    body_entries = [entry for entry in geometry if id(entry) not in strip_ids]

    for strip in strip_rows:
        strip_bgs = [_measure(image, x0, y0, x1, y1)[0] for _, x0, y0, x1, y1 in strip]
        strip_fgs = [_measure(image, x0, y0, x1, y1)[1] for _, x0, y0, x1, y1 in strip]
        _apply_region(strip, image, "menu_strip", strip_bgs, strip_fgs,
                      min_fg_distance=STRIP_OUTLIER_FLOOR,
                      min_population=3, use_runner_up=True)

    body_fgs = [_measure(image, x0, y0, x1, y1)[1] for _, x0, y0, x1, y1 in body_entries]
    screen_bg_ref = [screen_bg] if len(geometry) else []
    _apply_region(body_entries, image, "body", screen_bg_ref, body_fgs,
                  min_fg_distance=MIN_FG_DISTANCE,
                  min_population=MIN_LINES_FOR_FG_REF, use_runner_up=False)

    return [int(c) for c in screen_bg]
