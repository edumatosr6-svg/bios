"""Driving the BIOS by pointer: where the mouse is, and how to aim it.

**Why this exists alongside the keyboard path.** `navigate.py`'s anchored
sidebar walk works, but only because it encodes hard-won, model-specific
facts about this BIOS: that the sidebar does not wrap, that its top
element is a back arrow rather than the first menu entry, that reaching
entry *i* therefore costs `i + 1` presses. A different BIOS model -- and
the factory serves three -- may order things differently, wrap, or have
no arrow at all, and every one of those facts would have to be
rediscovered. Pointing at text OCR already found needs none of it.

That is the trade this module is for: **not speed** (measured end to end,
the keyboard path is still slightly faster), but not having to know the
menu's structure in advance.

**What makes aiming trustworthy here.** The cable only moves the pointer
in relative steps -- there is no "go to x,y" -- so position has to be
tracked. Three measured facts make that workable:

* movement is **linear, no acceleration** (~1.25px per small step,
  confirmed at 10/20/40-step probes on the second Positivo unit);
* the pointer is **visible**, so its position can be read off a frame
  diff rather than assumed;
* **but it is not always drawn.** Left idle a few seconds it stops being
  rendered entirely, and the next move then produces one diff blob (it
  appearing) instead of two (leaving, arriving). Every probe here wakes
  it first for exactly this reason.

Dead reckoning aims; a fresh frame diff confirms before any click. A
click is a commit, and nothing commits on arithmetic alone.
"""
from __future__ import annotations

import cv2
import numpy as np

# Small-step ratio measured live on the second Positivo unit at 1280x720
# HDMI. Only a fallback: `calibrate()` measures the real ratio per run,
# because it can differ with capture resolution.
FALLBACK_PX_PER_STEP = 1.25

DIFF_THRESHOLD = 30
BLOB_MIN_SIZE = 3
BLOB_MAX_SIZE = 120
# The pointer icon's bounding box is roughly as tall as it is wide. A
# row's hover-highlight bar is not: ~800px wide by ~20px tall (aspect
# ~40:1) when a content row lights up as the pointer crosses it. That bar
# can have a similar TOTAL area to a real blob after antialiasing, so
# area alone does not separate them -- a numeric ratio filter was defeated
# by exactly this. No pointer icon is forty times wider than it is tall;
# shape is what area cannot fake.
BLOB_MAX_ASPECT = 3.0
BLOB_MAX_DIM = 40

SEARCH_MARGIN = 150
PROBE_STEPS = 35
WAKE_STEPS = 3
# How far the confirm-nudge moves. It must exceed the pointer icon's own
# width, or the before/after positions overlap and merge into a SINGLE
# connected component -- and a single blob cannot be read as "it was here,
# now it is there". Measured directly 2026-08-26 at ~1.25px/step: 2 steps
# (~2px) -> 1 blob, 5 and 10 steps -> 0 usable blobs, 15 steps (~19px) ->
# 2 clean blobs. The original 2 was far too small, which silently turned
# every confirmation into unverified dead reckoning (see `move_to`).
CONFIRM_STEPS = 15


def fresh_frame(session):
    """A settled frame reflecting the machine's state *now*, without OCR.

    Position tracking never needs text, and `read_cursor()` would run a
    full OCR pass on the same settled frame -- measured, that alone made
    calibration cost 17s instead of 8s.
    """
    session._dirty = True
    return session.wait_stable()[-1]


def pointer_blobs(diff, search_region=None):
    """Changed regions plausibly the pointer, not on-screen noise.

    `search_region` (x0, y0, x1, y1) masks the diff before labelling --
    the strongest filter available once a position estimate exists, since
    it excludes by location rather than guessing from shape. Shape and
    size caps are what has to hold on the very first, region-less probe.
    """
    mask = (diff.max(axis=2) > DIFF_THRESHOLD).astype(np.uint8)
    if search_region is not None:
        x0, y0, x1, y1 = search_region
        height, width = mask.shape
        keep = np.zeros_like(mask)
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(width, int(x1)), min(height, int(y1))
        keep[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
        mask = keep

    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8)
    blobs = []
    for i in range(1, count):
        area = stats[i, cv2.CC_STAT_AREA]
        box_w = stats[i, cv2.CC_STAT_WIDTH]
        box_h = stats[i, cv2.CC_STAT_HEIGHT]
        if not (BLOB_MIN_SIZE <= area <= BLOB_MAX_SIZE):
            continue
        if box_w > BLOB_MAX_DIM or box_h > BLOB_MAX_DIM:
            continue
        if max(box_w, box_h) / max(1, min(box_w, box_h)) > BLOB_MAX_ASPECT:
            continue
        blobs.append((centroids[i][0], centroids[i][1], area))
    return blobs


class PointerUnavailable(RuntimeError):
    """The pointer could not be located -- this BIOS may not accept mouse
    input at all, or the pointer is not being drawn. Distinct from a
    normal navigation miss: it means "use the keyboard path", not "the
    screen said something unexpected"."""


class Pointer:
    """Tracks the pointer's pixel position and aims it at a target."""

    def __init__(self, session):
        self.session = session
        self.x = None
        self.y = None
        self.px_per_step_x = FALLBACK_PX_PER_STEP
        self.px_per_step_y = FALLBACK_PX_PER_STEP

    # -- locating ---------------------------------------------------------

    def _search_region(self, extra_margin=0):
        if self.x is None:
            return None
        margin = SEARCH_MARGIN + extra_margin
        return (self.x - margin, self.y - margin,
                self.x + margin, self.y + margin)

    def _noise_locations(self, tries=2):
        """Blob positions that appear with NO pointer movement at all.

        Excluding an observed location is not the same as guessing a
        threshold. A fixed blob (something animating in the content area)
        defeated every numeric filter tried -- size, region, and
        displacement ratio -- because whatever produces it happened to
        land inside each one. Its *location* is what it cannot hide.
        """
        locations = []
        for _ in range(tries):
            before = fresh_frame(self.session)
            after = fresh_frame(self.session)
            for x, y, _area in pointer_blobs(cv2.absdiff(before, after)):
                locations.append((x, y))
        return locations

    def _probe_axis(self, direction, steps=PROBE_STEPS, exclude=(), retries=2):
        """Move a known amount and measure the result, or None.

        Pairs blobs by plausibility rather than taking the two extremes
        along the axis: with unrelated blobs on screen, "furthest along
        the axis" pairs the pointer with noise instead of with itself.
        """
        # Wake before every probe: an idle gap (a slow read, a pause
        # between calls) is enough for the pointer to stop being drawn,
        # and then only one blob appears where two are needed.
        self.session.mouse_move(direction, steps=2)
        before = fresh_frame(self.session)
        self.session.mouse_move(direction, steps=steps)
        after = fresh_frame(self.session)

        region = self._search_region(extra_margin=(steps + 2) * 3)
        blobs = pointer_blobs(cv2.absdiff(before, after), search_region=region)
        if exclude:
            blobs = [b for b in blobs
                     if not any(abs(b[0] - nx) < 20 and abs(b[1] - ny) < 20
                                for nx, ny in exclude)]
        if len(blobs) < 2:
            # Retry rather than fail: what goes wrong here is transient --
            # the pointer caught mid-decay, or its vacated position
            # swallowed by a hover-highlight blob that shape-filtering
            # then removed along with it.
            if retries > 0:
                return self._probe_axis(direction, steps, exclude, retries - 1)
            return None

        axis = 0 if direction in ("left", "right") else 1
        sign = -1 if direction in ("left", "up") else 1

        candidates = []
        for start in blobs:
            for end in blobs:
                if start is end:
                    continue
                delta = (end[axis] - start[axis]) * sign
                if delta <= 0:
                    continue
                measured = delta / steps
                # A blinking element unrelated to the pointer jitters by a
                # roughly CONSTANT number of pixels, so its apparent ratio
                # shrinks as `steps` grows while a real pointer's holds --
                # which is why probes are deliberately large.
                if not (0.7 <= measured <= 2.0):
                    continue
                area_ratio = (max(start[2], end[2])
                              / max(1, min(start[2], end[2])))
                candidates.append((area_ratio, end, measured))
        if not candidates:
            return None
        _ratio, end, measured = min(candidates, key=lambda c: c[0])
        return end[0], end[1], measured

    def calibrate(self, steps=PROBE_STEPS):
        """Locate the pointer and measure px-per-step on both axes.

        Raises `PointerUnavailable` when the pointer cannot be found at
        all -- which is the signal to fall back to the keyboard, not an
        error to propagate to a user.
        """
        self.session.mouse_move("right", steps=WAKE_STEPS)
        fresh_frame(self.session)
        noise = self._noise_locations()

        for direction in ("right", "left"):
            found = self._probe_axis(direction, steps, exclude=noise)
            if found:
                self.x, self.y, self.px_per_step_x = found
                break
        else:
            raise PointerUnavailable(
                "nao localizei o ponteiro no eixo X -- esta BIOS aceita mouse?")

        for direction in ("down", "up"):
            found = self._probe_axis(direction, steps, exclude=noise)
            if found:
                self.x, self.y, self.px_per_step_y = found
                break
        else:
            raise PointerUnavailable(
                "nao localizei o ponteiro no eixo Y -- esta BIOS aceita mouse?")
        return self.x, self.y

    # -- aiming -----------------------------------------------------------

    def move_to(self, target_x, target_y, tolerance=8, max_corrections=2,
                on_step=None):
        """Aim by dead reckoning, then confirm against a fresh frame.

        Returns True only when the pointer's *measured* position is within
        `tolerance` of the target. Arithmetic is trusted to aim and never
        to confirm -- callers click on the strength of this return value.
        """
        for attempt in range(max_corrections + 1):
            dx = target_x - self.x
            dy = target_y - self.y
            steps_x = round(abs(dx) / self.px_per_step_x)
            steps_y = round(abs(dy) / self.px_per_step_y)
            if steps_x:
                self.session.mouse_move("right" if dx > 0 else "left",
                                        steps=steps_x)
                self.x += steps_x * self.px_per_step_x * (1 if dx > 0 else -1)
            if steps_y:
                self.session.mouse_move("down" if dy > 0 else "up",
                                        steps=steps_y)
                self.y += steps_y * self.px_per_step_y * (1 if dy > 0 else -1)

            # A nudge and back, purely to produce a diff the real position
            # can be read from. `CONFIRM_STEPS` is sized to clear the
            # icon's own width -- see that constant.
            before = fresh_frame(self.session)
            self.session.mouse_move("right", steps=CONFIRM_STEPS)
            after = fresh_frame(self.session)
            blobs = pointer_blobs(cv2.absdiff(before, after),
                                  search_region=self._search_region(
                                      extra_margin=CONFIRM_STEPS * 3))
            # Pick the PAIR whose separation matches the nudge we just
            # made, not simply the rightmost blob. "Rightmost" silently
            # picks an unrelated artifact whenever one happens to sit
            # further right than the pointer -- observed directly: one
            # confirmation reported a position 56px off target, which the
            # correction pass then had to undo. A wrong "measured"
            # position is worse than none, because it is trusted.
            expected = CONFIRM_STEPS * self.px_per_step_x
            pair = None
            for start in blobs:
                for end in blobs:
                    if start is end:
                        continue
                    dx = end[0] - start[0]
                    if abs(dx - expected) > max(6.0, expected * 0.4):
                        continue
                    if abs(end[1] - start[1]) > 6.0:   # a sideways nudge
                        continue
                    if pair is None or abs(dx - expected) < pair[0]:
                        pair = (abs(dx - expected), end)
            measured = pair is not None
            if measured:
                self.x, self.y = pair[1][0], pair[1][1]
            self.session.mouse_move("left", steps=CONFIRM_STEPS)
            self.x -= CONFIRM_STEPS * self.px_per_step_x

            error = ((self.x - target_x) ** 2 + (self.y - target_y) ** 2) ** 0.5
            if on_step:
                on_step(attempt, self.x, self.y, error, measured)

            # **Only a MEASURED position may confirm.** The version this
            # replaces fell through to dead reckoning whenever the nudge
            # produced too few blobs, and then returned True on the
            # strength of arithmetic that nothing had checked -- so a
            # caller clicked believing the position was verified when it
            # never was. That is the worst shape of error here: confidently
            # wrong rather than uncertain. Unmeasured now means try again,
            # and if it never measures, say so by returning False.
            if measured and error <= tolerance:
                return True
        return False


def click_point(session, pointer, x, y, tolerance=8):
    """Aim at a point and click it, or refuse. Never clicks unconfirmed."""
    if not pointer.move_to(x, y, tolerance=tolerance):
        return False
    session.mouse_click("left")
    return True
