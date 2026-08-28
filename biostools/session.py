"""One open connection to the machine under test, shared by every tool.

A `BiosSession` owns the three expensive things a tool needs -- the
camera, a *warm* perception pipeline, and the serial cable -- and hands
them to any number of tools. That sharing is the whole point: a tool is
allowed to call another tool, and paying the OCR model load on each call
would make composition unaffordable.

Warm pipeline, specifically: `perception.perceive()` rebuilds its
`Extraction` stage on every call, which reloads the OCR model
(`perception/__init__.py:110`). Fine for a one-shot CLI, unacceptable in
a navigate loop that reads the screen once per keypress. The fix is the
one `watcher.py:69-92` and `gui.py` already use -- build the ten
post-acquisition stages once and prepend a fresh `Acquisition` per read.

No signal handlers are installed here. Releasing the camera on SIGTERM
matters on Windows (an abrupt kill leaves the device locked for the next
process) but hijacking process-wide signals is not a library's business;
`__main__.py` does it for the CLI.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import cv2

from capture import open_camera, resolve_camera_source
from ocr import DEFAULT_ENGINE

DEFAULT_RESOLUTION = (1280, 720)

# Frames discarded right after opening the camera. A webcam opens with
# auto-exposure and autofocus still settling and those frames are darker
# and softer than what it will actually deliver. An HDMI capture card has
# no such warm-up, but the cost is a fraction of a second and the same
# code serves both inputs.
WARMUP_FRAMES = 8

# Frames dropped after a keypress before believing anything the camera
# says. Sized to comfortably exceed any driver-side queue depth; at ~30fps
# this costs a fraction of a second, paid only when a key was actually
# sent. See `BiosSession._flush` for what it prevents.
FLUSH_FRAMES = 12


@dataclass
class Reading:
    """One perception of the screen."""
    full: dict
    digest: dict
    frame: object
    captured_at: str

    @property
    def contract(self):
        return {"digest": self.digest, "full": self.full}


class CameraUnavailable(RuntimeError):
    pass


class ActuatorUnavailable(RuntimeError):
    """A key had to be pressed but the session has no cable attached."""


class BiosSession:
    """Camera + warm perception pipeline + (optional) actuator.

    The actuator is optional so a read-only tool can run with no cable
    attached; anything that tries to press a key without one gets a clear
    error rather than a confusing AttributeError.
    """

    def __init__(self, camera_source=0, serial_port=None,
                 engine=DEFAULT_ENGINE, resolution=DEFAULT_RESOLUTION,
                 frames=1, ocr_votes=1,
                 stable_threshold=1.5, stable_frames_required=3,
                 poll_interval=0.1, settle_timeout=6.0):
        self.engine = engine
        self.frames = max(1, frames)
        self.ocr_votes = max(1, ocr_votes)
        self.stable_threshold = stable_threshold
        self.stable_frames_required = stable_frames_required
        self.poll_interval = poll_interval
        self.settle_timeout = settle_timeout

        self.cap = self._open_camera(camera_source, resolution)
        self.actuator = None
        if serial_port:
            from actuator import BiosActuator

            self.actuator = BiosActuator(serial_port)

        self._warm = None    # perception stages, built lazily on first read
        self._legacy = None  # OCR engine for the cursor path, same lazily
        self._dirty = False  # a press happened since the buffer was last drained

    # -- lifecycle -------------------------------------------------------

    @staticmethod
    def _open_camera(camera_source, resolution):
        source = resolve_camera_source(camera_source)
        # capture.open_camera, not cv2.VideoCapture: the default Windows
        # backend takes 25s+ to open a device here. See its docstring.
        cap = open_camera(source)
        if not cap.isOpened():
            raise CameraUnavailable(
                f"could not open camera {camera_source!r}. "
                f"Use capture.list_camera_devices() to see which indices work."
            )
        width, height = resolution
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))) != (width, height):
            # Many USB cameras can only reach their higher modes as MJPG.
            # Asked for only when the plain request was refused, because
            # MJPG's compression artefacts land on the glyph edges OCR
            # depends on -- same reasoning as perception/run.py:148.
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        # Ask the driver to keep the shallowest queue it will allow. Not
        # honoured by every backend, which is why `_flush` below exists as
        # well rather than instead -- belt and braces, because a stale
        # frame here is not a cosmetic problem (see `press`).
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        for _ in range(WARMUP_FRAMES):
            cap.read()
        return cap

    def _build_warm(self):
        """The ten post-acquisition stages, constructed once.

        Imported here rather than at module scope so `import biostools`
        stays cheap -- listing the available tools must not load an OCR
        model.
        """
        from perception.stages import (
            Characterisation, Conditioning, Equivalence, Extraction, Grouping,
            Identity, Regionalisation, Serialisation, StateInference, Typing,
        )

        # Share one OCR engine instance with the legacy cursor path instead
        # of letting Extraction build its own. Measured 2026-08-24: each
        # engine instance pays its own cold start (~1.6-2.6s) the first
        # time it reads, and a tool run touches both paths (navigation
        # through `read_cursor`, the final field read through `read`), so
        # two instances meant paying that cost twice per session for no
        # reason -- same engine name, same weights. `_legacy_engine()`
        # builds it if the legacy path has not been used yet this session.
        return [
            Conditioning(),
            Extraction(engine=self.engine, ocr_votes=self.ocr_votes,
                      engine_instance=self._legacy_engine()),
            Characterisation(),
            Regionalisation(),
            Grouping(),
            Equivalence(),
            StateInference(),
            Typing(),
            Identity(),
            # "both": tools reason over `full` (geometry + classes), while
            # `digest` stays available for anything handing the screen to
            # an LLM later without breaking the architectural boundary.
            Serialisation(view="both"),
        ]

    def close(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if self.actuator is not None:
            self.actuator.close()
            self.actuator = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # -- reading ---------------------------------------------------------

    def grab(self, count=None):
        self._drain_if_dirty()
        count = count or self.frames
        frames = []
        for _ in range(count):
            ok, frame = self.cap.read()
            if ok:
                frames.append(frame)
        if not frames:
            raise CameraUnavailable("camera is open but returned no frames")
        return frames

    def read(self, frames=None):
        """Perceive the screen as it is right now, without waiting."""
        from perception.pipeline import run_pipeline
        from perception.stages import Acquisition

        if self._warm is None:
            self._warm = self._build_warm()

        frames = frames or self.grab()
        captured_at = time.strftime("%Y%m%d-%H%M%S")
        result = run_pipeline(
            [Acquisition(frames=frames, captured_at=captured_at)] + self._warm
        )
        contract = result.contract
        return Reading(
            full=contract["full"],
            digest=contract["digest"],
            frame=frames[-1],
            captured_at=captured_at,
        )

    def wait_stable(self, timeout=None):
        """Block until the screen stops changing, then return its frames.

        A keypress starts a redraw; reading mid-redraw measures a screen
        that no longer exists a moment later. Same mean-absdiff test
        `watcher.py:25` uses, but bounded by a timeout: a BIOS screen with
        a live sensor readout (a fan RPM ticking over) may never go
        completely still, and a tool must return an answer rather than
        wait forever for perfect stillness.
        """
        self._drain_if_dirty()
        timeout = self.settle_timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        prev_gray = None
        stable = 0

        while time.monotonic() < deadline:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(self.poll_interval)
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if prev_gray is not None:
                score = float(cv2.absdiff(prev_gray, gray).mean())
                stable = stable + 1 if score < self.stable_threshold else 0
                if stable >= self.stable_frames_required:
                    extra = self.grab(self.frames - 1) if self.frames > 1 else []
                    return [frame] + extra
            prev_gray = gray
            time.sleep(self.poll_interval)

        # Timed out: return what the camera shows now rather than raising.
        # The caller still verifies what it reads, so a slightly unsettled
        # frame costs an extra navigation step, not a wrong answer.
        return self.grab()

    def read_stable(self, timeout=None):
        return self.read(frames=self.wait_stable(timeout=timeout))

    # -- cursor reading (legacy path) ------------------------------------

    def _legacy_engine(self):
        if self._legacy is None:
            from ocr import create_ocr_engine

            self._legacy = create_ocr_engine(self.engine)
        return self._legacy

    def read_cursor(self, timeout=None, frames=None):
        """OCR + `selection.py`, for finding where the cursor is.

        Deliberately not the perception contract -- see the note above
        `screen.legacy_cursor` for the measurement that forced this split.
        Costs one OCR pass plus ~40ms, so navigating is as cheap as the
        chosen engine, with no need to fall back to a slow one.
        """
        from selection import annotate_selection

        frames = frames or self.wait_stable(timeout=timeout)
        frame = frames[-1]
        result = self._legacy_engine().read(frame)
        result["screen_bg_color"] = annotate_selection(frame, result["blocks"])
        result["frame"] = frame
        return result

    # -- acting ----------------------------------------------------------

    def press(self, key):
        if self.actuator is None:
            raise ActuatorUnavailable(
                "this session has no actuator -- pass serial_port=... to "
                "BiosSession to press keys (see actuator.list_serial_ports())"
            )
        self.actuator.press(key)
        # Marked, not flushed here -- see `_drain_if_dirty`. A caller that
        # sends several presses before ever reading again (exactly what
        # the anchored sidebar walk does: one `left` then up to eight
        # `up`s before the first read) would otherwise pay a ~0.5s drain
        # after every single one of them for no reason -- measured live
        # 2026-08-24, the difference between 0.06s and 0.53s per press.
        self._dirty = True

    def _require_actuator(self):
        if self.actuator is None:
            raise ActuatorUnavailable(
                "this session has no actuator -- pass serial_port=... to "
                "BiosSession to drive the machine "
                "(see actuator.list_serial_ports())"
            )

    def mouse_move(self, direction, steps=1, large=False):
        """Move the pointer, and mark the frame buffer dirty like `press`.

        Exists so mouse motion cannot bypass the staleness guard. Driving
        `session.actuator.mouse_move()` directly -- which every prototype
        did before this -- moves the machine without ever setting
        `_dirty`, so the next read is free to answer with a frame captured
        BEFORE the move. That is the same confidently-wrong failure
        `_drain_if_dirty` exists to prevent for keypresses, and it bit the
        mouse work for real (a pointer read as "not there" that had simply
        not been captured yet).
        """
        self._require_actuator()
        self.actuator.mouse_move(direction, steps=steps, large=large)
        self._dirty = True

    def mouse_click(self, button="left"):
        self._require_actuator()
        self.actuator.mouse_click(button)
        self._dirty = True

    def _drain_if_dirty(self, count=FLUSH_FRAMES):
        """Drop frames captured before now, so the next read cannot answer
        with the screen as it was *before* the last keypress.

        This is not an optimisation -- it fixes a real, and badly
        misleading, class of failure. `wait_stable` decides a screen has
        settled by comparing consecutive frames, and a queue of buffered
        frames from before the keypress are all identical to each other,
        so they pass that test perfectly and get returned as "the settled
        screen". The reading is then confidently wrong rather than
        uncertain, which is the worst shape an error can take here.

        Caught live 2026-08-24: a confirmation dialog had already been
        dismissed on the real machine, and two consecutive readings still
        showed it open, with the highlight detector happily reporting the
        dialog's 'Cancel' button. Only draining the queue revealed the
        actual current screen. Before this was understood, the same
        staleness read as "the BIOS is ignoring our keys" -- an entire
        investigation chased that instead.

        Called from every read path (`grab`, `wait_stable`), never from
        `press` itself, so a run of presses with no read between them (the
        common case in navigation) pays this exactly once, right before
        the read that actually needs it -- not once per press.
        """
        if not self._dirty:
            return
        self._dirty = False
        for _ in range(count):
            self.cap.read()
