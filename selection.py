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

Lines are grouped into regions in two clustering passes: first cluster
into ROWS by vertical position (any row of >= MIN_STRIP_SIZE lines is a
horizontal "menu_strip", e.g. a top tab bar); whatever's left is then
clustered into COLUMNS by horizontal position (any column of
>= MIN_STRIP_SIZE lines is a vertical "menu_column", e.g. a sidebar nav
or a list of submenu entries); everything still unclaimed is "body"
(compared against the whole-screen colour). A single frame can report
highlights in more than one region at once -- e.g. the active top-level
tab AND the focused item within it -- distinguished by each line's
`region` field. That is the answer to "should the active tab be reported
too": yes, as a same-shaped highlight with a different `region`, not a
separate concept.

Column detection was added after a real Positivo BIOS (vertical sidebar
menu, unlike the AMI BIOS's horizontal tab strip) scored 0/9 genuine
selections with rows alone -- every selected sidebar/submenu entry was
just judged as an unremarkable member of "body". Column x0 varies only
4-46px within a real menu column but by 400-2000px between columns
(sidebar / submenu-list / right-side icon strip), so the same gap-based
1D clustering used for rows works on the x-axis too.

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

* A menu strip/column is typically too small (4-19 items) for the body's
  MAD-based statistics to mean anything, and its floor
  (MIN_FG_DISTANCE=180, tuned against ~16-item body populations) rejected
  a real selection worth only 66.7 in a 5-item strip. Strips and columns
  instead use a scale-free "runner-up" test: the most different item must
  clearly beat the SECOND most different item (`STRIP_RUNNER_UP_RATIO`),
  which needs no absolute-distance calibration at all. This part has thin
  validation -- a handful of real screens -- so treat `STRIP_*` constants
  as provisional until the 3rd BIOS model is available; test_selection.py
  must still pass after any retune.

* `MAX_PERIMETER_STD` had to move from 34 to 50 once real (not synthetic)
  photos were available: a synthetic highlight bar is a perfectly flat
  fill (std=0), but a real one photographed through a camera has JPEG
  compression and lighting noise at its edges -- one genuine Positivo
  selection measured std=39.9, just over the old ceiling. Measured
  ordinary (non-selected) lines sit at p90 <= 11 across 5 real photos, so
  50 keeps a wide margin on both sides.

* Signal A's background-distance floor is NOT the same number for "body"
  vs "strip/column". Body compares a line against the whole-screen
  colour -- a busy, noisy reference where only a stark shift (250+) is
  trustworthy. A strip/column compares a line against a handful of
  visually-uniform siblings, where real Positivo selections measured
  d_bg=121-146 while every unselected sibling in the same group measured
  under 20 -- a much lower floor (`STRIP_MIN_BG_DISTANCE`) is both safe
  and necessary there, since 250 would silently miss all of them and fall
  through to the less reliable signal B below. Using one shared constant
  for both was the bug that made an early version of this fix look like
  it had failed.

* Signal B's "most different from the median" winner can pick the
  DESCRIPTION line adjacent to a true selection instead of the selection
  itself, when a column mixes menu items with their description text (the
  Positivo submenu list, where each entry has a one-line description
  directly beneath it) -- observed on one real photo, likely because a
  real highlight bar's edge bleeds slightly into the next line's bbox.
  Signal A is unaffected and, with the floor above, now fires first and
  finds the right line before signal B ever runs -- but if a future BIOS
  ever needs signal B inside a mixed items+descriptions column, revisit
  this rather than assume it's fixed.

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
MAX_PERIMETER_STD = 50.0       # signal A: a selection bar is a flat fill (see docstring)
MIN_FG_DISTANCE = 180.0        # signal B (body): absolute floor before MAD applies
MAD_MULTIPLIER = 8.0           # signal B (body): how far outside the spread to require
MIN_LINES_FOR_FG_REF = 4       # too few lines and the median text colour is noise
MAX_TEXT_COLOR_OUTLIERS = 1    # signal B: a region selects one entry, not many
RING = 2                       # perimeter ring thickness, px

# Menu-strip/menu-column (tab bar / sidebar / submenu list) thresholds --
# see docstring caveat above.
MIN_STRIP_SIZE = 4             # lines needed in a row/column before treating it as one
STRIP_MIN_BG_DISTANCE = 100.0  # signal A (strip/column): line bg vs its OWN group's bg
STRIP_OUTLIER_FLOOR = 60.0     # signal B (strip/column): minimum distance to even consider
STRIP_RUNNER_UP_RATIO = 2.2    # signal B (strip/column): winner must beat 2nd place by this much
ROW_GAP_FACTOR = 0.6           # row clustering: max vertical gap, x median line height
COLUMN_GAP_PX = 100.0          # column clustering: max horizontal gap between column-mates
CONTIGUITY_HEIGHT_FACTOR = 2.5 # row/column contiguity: max end-to-start gap, x median line height


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


def _cluster_1d(geometry, key_fn, gap):
    """Generic gap-based clustering: sort by key_fn, start a new group
    whenever the gap to the previous value exceeds `gap`.
    """
    if not geometry:
        return []
    ordered = sorted(geometry, key=key_fn)
    groups, current = [], [ordered[0]]
    prev = key_fn(ordered[0])
    for entry in ordered[1:]:
        value = key_fn(entry)
        if value - prev > gap:
            groups.append(current)
            current = []
        current.append(entry)
        prev = value
    groups.append(current)
    return groups


def _split_by_gaps(group, start_fn, end_fn, max_gap):
    """Split a candidate row/column into contiguous runs along its OWN
    axis, instead of just accepting or rejecting the whole group.

    A group clustered on one axis (e.g. same x0 -> "a column") can still
    contain items that have nothing to do with each other on the OTHER
    axis: a title, a row of labels, and a hotkey hint can all sit at the
    same left margin (x0) yet be worlds apart vertically. An early,
    binary accept/reject version of this check rejected such a group
    outright over one big gap anywhere in it (the title-to-hotkey jump),
    which also threw away the perfectly good, contiguous run of labels in
    the middle. Splitting into runs keeps that run as its own candidate.

    Gaps are measured end-of-previous-item to start-of-next, not
    start-to-start: two adjacent menu words like "Boot" (narrow) and
    "Security" (wide) sit right next to each other with only ~20px of
    real whitespace between them, but 100-200px apart start-to-start
    purely because of how wide "Boot" itself is -- start-to-start would
    split a genuine row on word-width alone. End-to-start isolates the
    actual gap: ~15-25px on measured genuine rows/columns, vs. the
    hundreds of px an unrelated item sits away.
    """
    if len(group) < 2:
        return [group]
    ordered = sorted(group, key=start_fn)
    runs, current = [], [ordered[0]]
    for prev, item in zip(ordered, ordered[1:]):
        if start_fn(item) - end_fn(prev) > max_gap:
            runs.append(current)
            current = []
        current.append(item)
    runs.append(current)
    return runs


def _median_height(group):
    return float(np.median([y1 - y0 for _, _, y0, _, y1 in group])) if group else 0.0


def _cluster_rows(geometry):
    """Cluster by vertical centre: a new row starts when the gap to the
    previous centre exceeds ROW_GAP_FACTOR x the median line height on
    this screen -- catches horizontal groupings like a top tab bar. Each
    candidate is then split into contiguous runs along X (real inter-word
    gaps measured at 13-23px, scaled here by CONTIGUITY_HEIGHT_FACTOR x
    line height so it scales across image resolutions), since sharing a Y
    coordinate doesn't by itself mean the items are related -- see
    `_split_by_gaps`.
    """
    if not geometry:
        return []
    heights = [y1 - y0 for _, _, y0, _, y1 in geometry]
    gap = ROW_GAP_FACTOR * float(np.median(heights))
    candidates = _cluster_1d(geometry, lambda e: (e[2] + e[4]) / 2, gap)
    return [run for group in candidates
            for run in _split_by_gaps(group, lambda e: e[1], lambda e: e[3],
                                      CONTIGUITY_HEIGHT_FACTOR * _median_height(group))]


def _cluster_columns(geometry):
    """Cluster by left edge (x0): a new column starts when the gap
    exceeds COLUMN_GAP_PX -- catches vertical groupings like a sidebar
    nav or a list of submenu entries. Fixed-pixel gap rather than a
    relative one: unlike row height, column x0 spacing isn't naturally
    tied to any per-screen measurement, and 100px comfortably separates
    real columns (400-2000px apart) from within-column jitter (4-46px)
    on every photo measured so far. Each candidate is then split into
    contiguous runs along Y -- sharing a left margin doesn't by itself
    mean items are related (observed: a title, a column of labels, and a
    hotkey hint all sharing x0 merged into one useless blob before this
    split was added) -- see `_split_by_gaps`.
    """
    candidates = _cluster_1d(geometry, lambda e: e[1], COLUMN_GAP_PX)
    return [run for group in candidates
            for run in _split_by_gaps(group, lambda e: e[2], lambda e: e[4],
                                      CONTIGUITY_HEIGHT_FACTOR * _median_height(group))]


def _apply_region(entries, image, region_name, bg_reference, fg_population,
                  min_bg_distance, min_fg_distance, min_population, use_runner_up):
    """Shared signal A + signal B logic for one region's lines, against
    that region's own reference colours (`bg_reference`/`fg_population`).
    """
    measured = [(line, x0, y0, x1, y1, *_measure(image, x0, y0, x1, y1))
                for line, x0, y0, x1, y1 in entries]
    for line, *_rest, bg, fg, _std in measured:
        line["bg_color"] = [int(c) for c in bg]
        line["fg_color"] = [int(c) for c in fg]

    bg_center = np.median(bg_reference, axis=0) if len(bg_reference) else None
    bar_candidates = []
    if bg_center is not None:
        for line, *_geom, bg, fg, std in measured:
            d_bg = _color_distance(bg, bg_center)
            if (d_bg > min_bg_distance and std <= MAX_PERIMETER_STD
                    and _color_distance(fg, bg_center) < d_bg):
                bar_candidates.append((d_bg, line))

    bar_hit = None
    if bar_candidates:
        # A region has one genuine selection; a lenient enough bg floor to
        # catch subtle real photos (see STRIP_MIN_BG_DISTANCE) can also let
        # ordinary photo noise clear it on more than one line at once, so
        # -- same discipline as signal B -- only trust the single strongest
        # candidate, and only if it clearly leads the runner-up.
        bar_candidates.sort(key=lambda pair: pair[0])
        winner_d, winner_line = bar_candidates[-1]
        runner_up_d = bar_candidates[-2][0] if len(bar_candidates) >= 2 else 0.0
        if winner_d > STRIP_RUNNER_UP_RATIO * max(runner_up_d, 1.0):
            bar_hit = winner_line

    if bar_hit is not None:
        bar_hit["highlighted"] = True
        bar_hit["region"] = region_name
    if bar_hit is not None or len(fg_population) < min_population:
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
    (bool), `region` ("menu_strip" | "menu_column" | "body" | None), `bg_color`, `fg_color`
    (BGR, matching the input image). Returns the screen's overall
    background colour for reference. A single frame can report highlights
    in more than one region at once (e.g. an active tab AND a focused
    body item), since each is judged against its own region's colours.
    """
    screen_bg = np.median(image.reshape(-1, 3), axis=0)
    geometry = _line_geometry(image, blocks)

    rows = _cluster_rows(geometry)
    strip_rows = [row for row in rows if len(row) >= MIN_STRIP_SIZE]
    claimed = {id(entry) for row in strip_rows for entry in row}

    unclaimed = [entry for entry in geometry if id(entry) not in claimed]
    columns = _cluster_columns(unclaimed)
    strip_columns = [col for col in columns if len(col) >= MIN_STRIP_SIZE]
    claimed |= {id(entry) for col in strip_columns for entry in col}

    body_entries = [entry for entry in geometry if id(entry) not in claimed]

    for strip, region_name in [(s, "menu_strip") for s in strip_rows] + \
                              [(c, "menu_column") for c in strip_columns]:
        strip_bgs = [_measure(image, x0, y0, x1, y1)[0] for _, x0, y0, x1, y1 in strip]
        strip_fgs = [_measure(image, x0, y0, x1, y1)[1] for _, x0, y0, x1, y1 in strip]
        _apply_region(strip, image, region_name, strip_bgs, strip_fgs,
                      min_bg_distance=STRIP_MIN_BG_DISTANCE,
                      min_fg_distance=STRIP_OUTLIER_FLOOR,
                      min_population=3, use_runner_up=True)

    body_fgs = [_measure(image, x0, y0, x1, y1)[1] for _, x0, y0, x1, y1 in body_entries]
    screen_bg_ref = [screen_bg] if len(geometry) else []
    _apply_region(body_entries, image, "body", screen_bg_ref, body_fgs,
                  min_bg_distance=MIN_BG_DISTANCE,
                  min_fg_distance=MIN_FG_DISTANCE,
                  min_population=MIN_LINES_FOR_FG_REF, use_runner_up=False)

    return [int(c) for c in screen_bg]
