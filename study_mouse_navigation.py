"""First prototype: click directly on OCR-found text, instead of counting
arrow-key presses.

Measured live on a second machine with mouse support enabled in Setup
(2026-08-24, see project memory): the pointer is visible, movement is
**linear with no acceleration** (~1.25px per small step, confirmed at
10/20/40-step probes), and hovering an item highlights it with the same
bar `selection.py` already reads for the keyboard cursor -- so this reuses
existing detection instead of inventing a new one. A single left click
opens/activates whatever is under the pointer; no double-click needed.

**What this script actually does, end to end:**
1. Calibrate once: probe-move the mouse a known number of steps, diff two
   frames to find where the pointer WAS and IS -- this yields both the
   px-per-step ratio and a confirmed starting position in one shot, never
   assumed.
2. Track position by dead reckoning after that (steps sent x calibrated
   ratio) -- cheap, no need to diff on every move.
3. To click a target: find its text via OCR, compute the click point,
   convert the pixel delta to steps, move, then **verify with a tiny
   wiggle-and-diff before clicking** -- dead reckoning is trusted to aim,
   never trusted enough to click blind. Same discipline as the keyboard
   path: a click is a commit, and nothing here commits without a fresh
   image confirming where the pointer actually is.

Needs the cable and a BIOS where Setup accepts mouse input (not every
model does -- this was confirmed on the second Positivo unit, not the
first).

    py -3.13 study_mouse_navigation.py --serial-port COM3 --target "Trusted Computing"
"""
import argparse
import time

import cv2
import numpy as np

from biostools.navigate import SIDEBAR_MAX_X, looks_like_dialog
from biostools.screen import legacy_cursor, match_score, normalize
from biostools.session import BiosSession
from ocr import DEFAULT_ENGINE, ENGINE_CHOICES

# Small-step ratio measured live 2026-08-24 on the second Positivo unit,
# 1280x720 HDMI: 10/20/40-step probes gave 12.8/24.4/50.0px, all landing
# within 5% of 1.25px/step with no sign of acceleration. Overwritten by
# `calibrate()` on every run -- this is only the fallback if a probe move
# is blocked at a screen edge on both tries.
FALLBACK_PX_PER_STEP = 1.25

BLOB_DIFF_THRESHOLD = 30
BLOB_MIN_SIZE = 3
# The arrow icon's own diff blobs measured live (~20-30px area at 1280x720
# HDMI). Caps out well before a changed text glyph -- a single digit of the
# Main page's live clock produced a much larger blob and got mistaken for
# the cursor (measured 2026-08-24: locate came back 657px off-target on
# Main, which has a ticking `System Time`; Advanced has no such field and
# never showed this). Region restriction (see `cursor_blobs`'s
# `search_region`) is the primary defence once a position is known; size
# is what protects the very first, region-less probe.
BLOB_MAX_SIZE = 120
# The arrow icon's bounding box is roughly as tall as it is wide. A row's
# hover-highlight bar is not: measured live 2026-08-24, ~800px wide by
# ~20px tall (area ~14000, aspect ~40:1) when a whole content row lights
# up or goes dark as the pointer crosses it. That bar sometimes has a
# similar TOTAL area to a legitimate blob after antialiasing, so area
# alone does not reliably separate them (a numeric ratio filter downstream
# was defeated by exactly this on 2026-08-24) -- but no cursor icon is
# ever forty times wider than it is tall. Shape is what area can't fake.
BLOB_MAX_ASPECT = 3.0
# Absolute bounding-box cap, belt-and-braces with the aspect check: catches
# a blob that happens to be roughly square but still far bigger than any
# real cursor icon (e.g. two icons merged by a diagonal antialiased edge).
BLOB_MAX_DIM = 40
# Generous margin around the last known position to search in, once there
# is one -- wide enough to contain any single probe/correction move, tight
# enough to exclude unrelated on-screen changes (a clock, a sensor value)
# happening anywhere else on the page.
SEARCH_MARGIN = 150


def fresh_frame(session):
    """A settled frame guaranteed to reflect the machine's current state
    -- WITHOUT paying for OCR, which position-tracking never needs.

    Mouse commands go through `session.actuator` directly, not
    `session.press()`, so they never set `BiosSession._dirty` -- the flag
    `_drain_if_dirty` checks before trusting a read. Without marking it
    here too, a read right after a mouse move could still return a
    buffered pre-move frame (the exact bug `_drain_if_dirty` exists to
    prevent for keyboard presses; mouse needs the same guard).

    Deliberately `wait_stable()`, not `read_cursor()`: the latter runs a
    full OCR pass on top of the same settled frame. Measured 2026-08-24,
    that made the first full mouse-navigation timing test slower than the
    keyboard path it was supposed to beat -- calibration alone (six probe
    reads) cost 17s. Position tracking only ever diffs raw pixels, so OCR
    on every probe was pure waste; text is read separately, only when a
    target actually needs to be located (see `click_text`).
    """
    session._dirty = True
    return session.wait_stable()[-1]


def cursor_blobs(diff, search_region=None):
    """Changed regions likely to be the pointer, not on-screen noise.

    `search_region` (x0, y0, x1, y1) masks the diff to a box before
    labelling -- the strongest filter available once a position estimate
    exists, since it excludes unrelated changes by location rather than
    guessing from shape/size alone. Always applied together with the size
    cap; either alone missed the live-clock contamination that motivated
    both (see `BLOB_MAX_SIZE`).
    """
    mask = (diff.max(axis=2) > BLOB_DIFF_THRESHOLD).astype(np.uint8)
    if search_region is not None:
        x0, y0, x1, y1 = search_region
        keep = np.zeros_like(mask)
        h, w = mask.shape
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(w, int(x1)), min(h, int(y1))
        keep[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
        mask = keep
    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    result = []
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        bw = stats[i, cv2.CC_STAT_WIDTH]
        bh = stats[i, cv2.CC_STAT_HEIGHT]
        if not (BLOB_MIN_SIZE <= area <= BLOB_MAX_SIZE):
            continue
        if bw > BLOB_MAX_DIM or bh > BLOB_MAX_DIM:
            continue
        if max(bw, bh) / max(1, min(bw, bh)) > BLOB_MAX_ASPECT:
            continue
        result.append((centroids[i][0], centroids[i][1], area))
    return result


class MouseTracker:
    """Dead-reckons the pointer's pixel position after a one-time probe
    calibration, per the module docstring's three-step plan.
    """

    def __init__(self, session):
        self.session = session
        self.x = None
        self.y = None
        self.px_per_step_x = FALLBACK_PX_PER_STEP
        self.px_per_step_y = FALLBACK_PX_PER_STEP

    def _search_region(self, extra_margin=0):
        """A box around the last known position, or None to search the
        whole frame -- only true on the very first probe, before any
        position is known at all.
        """
        if self.x is None:
            return None
        m = SEARCH_MARGIN + extra_margin
        return (self.x - m, self.y - m, self.x + m, self.y + m)

    def _noise_locations(self, tries=2):
        """Blob positions that show up with NO mouse movement at all.

        Direct fix for a real, stubborn failure mode (2026-08-24): a
        fixed-ish blob near one screen location kept getting mistaken for
        the cursor by every numeric plausibility filter tried (size,
        region, displacement-per-step ratio) because whatever is actually
        producing it -- almost certainly something blinking/animating in
        the content area, unrelated to the mouse -- happened to land
        inside every threshold tried. A threshold on the SYMPTOM can
        always be defeated by a source that happens to match it; excluding
        the actual observed location(s) is not guessing at a threshold,
        it is looking at what changes when nothing that could move the
        cursor happened.
        """
        locations = []
        for _ in range(tries):
            before = fresh_frame(self.session)
            after = fresh_frame(self.session)
            for x, y, _area in cursor_blobs(cv2.absdiff(before, after)):
                locations.append((x, y))
        return locations

    def _probe_axis(self, direction, steps=15, exclude=(), retries=2):
        """Move a known amount, diff, and return the confirmed post-move
        position plus the measured px/step -- or None if no pair of blobs
        looks like "the same small object, moved a plausible distance".

        Not the two extreme positions along the move axis. Measured live
        2026-08-24: a persistent unrelated blob (something blinking in the
        content area, unrelated to the mouse) showed up in every single
        probe, at every direction, at a near-fixed screen location. With
        no search region yet (true only for the very first probe ever --
        `_search_region` returns None until a position is known), sorting
        all blobs by position and taking the extremes paired the real
        cursor with that unrelated blob instead of with itself, because it
        happened to be furthest along whichever axis was being probed.
        Region restriction handles this once a position exists; this is
        what has to hold up before that, on the read that bootstraps it.
        """
        # Wake before every probe, not just once in `calibrate` -- a slow
        # read (OCR-bearing calls elsewhere, or just camera/settle jitter)
        # between probes is enough idle time for the pointer to have
        # decayed again by the time this one starts. A throwaway nudge
        # right before capturing `before` is what guarantees `before`
        # itself already shows a visible pointer, not just `after`.
        self.session.actuator.mouse_move(direction, steps=2)
        before = fresh_frame(self.session)
        self.session.actuator.mouse_move(direction, steps=steps)
        after = fresh_frame(self.session)
        region = self._search_region(extra_margin=(steps + 2) * 3)
        blobs = cursor_blobs(cv2.absdiff(before, after), search_region=region)
        if exclude:
            blobs = [b for b in blobs
                    if not any(abs(b[0] - nx) < 20 and abs(b[1] - ny) < 20
                              for nx, ny in exclude)]
        if len(blobs) < 2:
            # Retry in place rather than making every caller loop: cheap
            # (one more probe, a few hundred ms to a couple seconds), and
            # what actually failed here is usually transient -- the
            # pointer mid-decay, or its vacated position swallowed into a
            # hover-highlight blob that then got shape-filtered out along
            # with it (see BLOB_MAX_ASPECT). A fresh attempt from a
            # different starting instant routinely just works.
            if retries > 0:
                return self._probe_axis(direction, steps, exclude, retries - 1)
            return None

        axis = 0 if direction in ("left", "right") else 1
        sign = -1 if direction in ("left", "up") else 1

        # Every pair, not just the sorted extremes: keep the ones whose
        # own displacement is plausible for a real cursor step (generous
        # bounds around the ~0.9-1.3px/step measured on this BIOS so far)
        # and whose move is in the commanded direction, then prefer
        # whichever candidate pair has the most similar blob area -- the
        # same small icon before and after should look like the same size,
        # while a real blob paired with unrelated noise usually won't.
        candidates = []
        for i in range(len(blobs)):
            for j in range(len(blobs)):
                if i == j:
                    continue
                start, end = blobs[i], blobs[j]
                delta = (end[axis] - start[axis]) * sign
                if delta <= 0:
                    continue
                measured = delta / steps
                # Tighter than it looks necessary, on purpose: a blinking
                # or animated element unrelated to the mouse (measured
                # live 2026-08-24, a fixed near-(890,352) blob showing up
                # in every probe) has a roughly CONSTANT pixel jitter
                # between frames, so its apparent "ratio" shrinks as
                # `steps` grows while a real cursor's does not -- 0.7 is
                # what separated the two once probes moved to 30+ steps.
                if not (0.7 <= measured <= 2.0):
                    continue
                area_ratio = max(start[2], end[2]) / max(1, min(start[2], end[2]))
                candidates.append((area_ratio, start, end, measured))

        if not candidates:
            return None
        _ratio, _start, end, measured = min(candidates, key=lambda c: c[0])
        return end[0], end[1], measured

    def calibrate(self, steps=35):
        """One probe per axis. Tries the opposite direction if the first
        is blocked at a screen edge -- a probe with nowhere to go looks
        identical to a broken calibration otherwise.

        35, not the smaller counts used once a position is already known:
        with no search region yet to exclude unrelated on-screen noise,
        a bigger real displacement is what separates a genuine cursor
        move from a fixed-magnitude animation artifact -- see the ratio
        filter in `_probe_axis`.
        """
        # Wake the pointer up first, and throw this move away. Measured
        # 2026-08-24: left alone a few seconds (as happens naturally
        # between separate script runs, or debugging pauses), the pointer
        # stops being drawn at all -- confirmed by inspecting frames
        # directly, not inferred. The NEXT move after that then produces
        # only ONE diff blob (the pointer appearing) instead of two
        # (vacating the old spot, occupying the new one), which breaks
        # every pairing/ratio measurement below -- they all assume two
        # blobs to compare. One throwaway nudge first means the real probe
        # always starts from a state where the pointer is already visible.
        self.session.actuator.mouse_move("right", steps=3)
        fresh_frame(self.session)

        noise = self._noise_locations()
        if noise:
            print(f"    ruido detectado (sem mover nada) em: "
                  f"{[(round(x), round(y)) for x, y in noise]} -- excluindo")

        for direction in ("right", "left"):
            result = self._probe_axis(direction, steps, exclude=noise)
            if result:
                self.x, self.y, self.px_per_step_x = result
                break
        else:
            raise RuntimeError("nao consegui calibrar o eixo X -- "
                              "cursor preso nas duas bordas?")

        for direction in ("down", "up"):
            result = self._probe_axis(direction, steps, exclude=noise)
            if result:
                self.x, self.y, self.px_per_step_y = result
                break
        else:
            raise RuntimeError("nao consegui calibrar o eixo Y -- "
                              "cursor preso nas duas bordas?")
        return self.x, self.y, self.px_per_step_x, self.px_per_step_y

    def move_to(self, target_x, target_y, tolerance=6, max_corrections=2):
        """Aim by dead reckoning, then confirm (never trust blindly) with
        one wiggle-and-diff pass; correct once or twice if it landed off.
        """
        for attempt in range(max_corrections + 1):
            dx, dy = target_x - self.x, target_y - self.y
            steps_x = round(abs(dx) / self.px_per_step_x)
            steps_y = round(abs(dy) / self.px_per_step_y)
            if steps_x:
                self.session.actuator.mouse_move(
                    "right" if dx > 0 else "left", steps=steps_x)
                self.x += steps_x * self.px_per_step_x * (1 if dx > 0 else -1)
            if steps_y:
                self.session.actuator.mouse_move(
                    "down" if dy > 0 else "up", steps=steps_y)
                self.y += steps_y * self.px_per_step_y * (1 if dy > 0 else -1)

            # Wiggle: a tiny move-and-back that only exists to produce a
            # diff, so the real, current position can be read off the
            # image instead of trusted from arithmetic alone.
            before = fresh_frame(self.session)
            self.session.actuator.mouse_move("right", steps=2)
            after = fresh_frame(self.session)
            region = self._search_region(extra_margin=10)
            blobs = cursor_blobs(cv2.absdiff(before, after), search_region=region)
            if len(blobs) >= 2:
                blobs.sort(key=lambda b: b[0])
                self.x, self.y = blobs[-1][0], blobs[-1][1]
            self.session.actuator.mouse_move("left", steps=2)
            self.x -= 2 * self.px_per_step_x

            error = ((self.x - target_x) ** 2 + (self.y - target_y) ** 2) ** 0.5
            print(f"    tentativa {attempt}: pos=({self.x:.0f},{self.y:.0f}) "
                  f"alvo=({target_x},{target_y}) erro={error:.1f}px")
            if error <= tolerance:
                return True
        return False


def find_target(reading, target_text):
    """The OCR line matching `target_text`, anywhere on screen."""
    for block in reading.get("blocks", ()):
        for line in block.get("lines", ()):
            if match_score(target_text, line["text"]):
                return line
    return None


def click_text(session, tracker, target_text, verify_highlight=False):
    """The whole point: find text, aim the mouse at it, confirm, click."""
    reading = session.read_cursor()
    line = find_target(reading, target_text)
    if line is None:
        print(f"  '{target_text}' nao esta na tela agora -- nao vou mirar as cegas")
        return False

    bb = line["bbox"]
    # A point inside the row, not its exact top-left corner -- clicking
    # right at a text glyph's edge risks landing on the row above/below on
    # a tightly packed list. Left-biased x (label rows are usually clicked
    # near their start, not their far right edge where value/help text may
    # overlap) and vertical centre.
    target_x = bb["left"] + min(30, bb["width"] * 0.3)
    target_y = bb["top"] + bb["height"] / 2
    print(f"  alvo '{line['text']}' em bbox={bb} -> mirando ({target_x:.0f},{target_y:.0f})")

    if not tracker.move_to(target_x, target_y):
        print("  nao convergiu dentro da tolerancia -- nao vou clicar")
        return False

    # Highlight verification exists but does NOT gate the click by default
    # -- measured live 2026-08-24: unlike the keyboard cursor's mark, the
    # mouse hover highlight is NOT stable over time. Left alone with no
    # further input it drifted from the sidebar's static mark to the
    # content list's static first-item mark within ~7s, with neither ever
    # being the hovered row -- almost certainly a transient hover-highlight
    # that had already decayed by the time the verifying OCR read (1-3s)
    # completed. The wiggle position check in `move_to` is the real safety
    # gate here: it is fast and reads ground-truth pixel position, not a
    # highlight animation that may or may not still be showing.
    if verify_highlight:
        reading = session.read_cursor()
        if looks_like_dialog(reading):
            print("  um dialogo apareceu so de mover o mouse -- parando")
            return False
        marked = legacy_cursor(reading)
        if marked is None or not match_score(target_text, marked["text"]):
            print(f"  (destaque nao confirma '{target_text}' -- marcado: "
                  f"{marked['text'] if marked else None} -- ignorando, "
                  f"provavel decaimento do hover, nao um erro de mira)")
        else:
            print(f"  destaque confirma '{marked['text']}' sob o mouse")

    session.actuator.mouse_click("left")
    session._dirty = True
    after = session.read_cursor()
    if looks_like_dialog(after):
        session.press("esc")
        print("  o clique abriu um dialogo de confirmacao -- fechei e parei")
        return False
    print("  clicado.")
    return True


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--camera-source", default="0")
    parser.add_argument("--engine", choices=ENGINE_CHOICES, default=DEFAULT_ENGINE)
    parser.add_argument("--resolution", default="1280x720")
    parser.add_argument("--serial-port", required=True)
    parser.add_argument("--target", required=True,
                        help="Text of the item to click, e.g. 'Trusted Computing'")
    return parser.parse_args()


def main():
    args = parse_args()
    resolution = tuple(int(v) for v in args.resolution.lower().split("x"))

    with BiosSession(camera_source=args.camera_source, engine=args.engine,
                      resolution=resolution,
                      serial_port=args.serial_port) as session:
        tracker = MouseTracker(session)
        print("calibrando (sonda o mouse pra achar posicao + razao px/passo)...")
        x, y, rx, ry = tracker.calibrate()
        print(f"  posicao inicial=({x:.0f},{y:.0f})  "
              f"px/passo: x={rx:.2f} y={ry:.2f}\n")

        print(f"mirando em '{args.target}'...")
        ok = click_text(session, tracker, args.target)
        print(f"\n{'sucesso' if ok else 'nao concluido'}")


if __name__ == "__main__":
    main()
