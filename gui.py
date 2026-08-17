"""Desktop GUI: live camera preview on one side, OCR result on the other.

Reuses the same automatic trigger logic as watcher.py (frame-diff
stability detection) -- when the camera feed on screen stops changing,
OCR runs automatically and the text panel updates. No manual button
press needed; there's also a manual "OCR now" button for on-demand
testing.

OCR runs in a separate OS *process*, not just a background thread.
PaddleOCR on CPU holds the GIL almost continuously for seconds at a
time during a single read() call, which starved the Tkinter main
thread badly enough that Windows reported the window as "Not
Responding" even with OCR on a background thread. A subprocess has its
own interpreter/GIL, so no matter how CPU-heavy OCR is, the GUI event
loop keeps pumping normally.

The camera itself is connected from inside the running app (a source
field + Connect button) rather than only at startup: the camera source
here is a phone streaming over wifi, which routinely drops/changes IP,
and connecting can block for a long time against a dead address. The
window always opens immediately; if no camera is connected the video
panel just says so instead of the whole app hanging or refusing to
start.
"""
import collections
import multiprocessing as mp
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

# Quiet the backend's per-frame chatter before OpenCV is imported. A lost
# camera logs a warning on every failed grab, which at 33 reads a second
# buries anything useful in the console.
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

import cv2

cv2.setLogLevel(0)
from PIL import Image, ImageTk

from capture import list_camera_devices, resolve_camera_source
from extract import DEFAULT_HOST, DEFAULT_MODEL, DEFAULT_PORT, ExtractionError
from ocr import DEFAULT_ENGINE, ENGINE_CHOICES
from sender import send_result


# 1280x720, not 1920x1080. More pixels is not more detail: measured on the
# UGREEN 4K webcam pointed at a BIOS screen, sharpness was 612 at 720p and
# 85 at 1080p -- the higher mode is interpolated, and the text goes from
# crisp to mush. Cameras advertise modes they cannot actually resolve, so
# the default is the resolution that survived measurement, and --resolution
# exists for hardware that does better.
REQUESTED_WIDTH, REQUESTED_HEIGHT = 1280, 720

# A camera that has gone away fails every read. Tolerate a few dropped
# frames, then treat it as lost -- see _on_read_failure.
MAX_CONSECUTIVE_READ_FAILURES = 30


def request_resolution(cap, width=REQUESTED_WIDTH, height=REQUESTED_HEIGHT):
    """Ask the camera for a resolution usable for BIOS text, and report
    what it actually gave.

    OpenCV opens a webcam at whatever the driver offers by default, which
    is routinely 640x480. That is fine for a video call and hopeless for
    BIOS menu text -- at that size there are not enough pixels per
    character for OCR to recognise anything, and the failure looks like
    "the OCR is bad" rather than "the image is too small".

    The plain request comes first and MJPG is only a fallback. Many USB
    webcams cannot carry their higher modes as raw YUY2 and need the codec
    switch to reach them -- but MJPG is compressed, and on text its
    artefacts land exactly on the glyph edges OCR depends on. Asking for
    the codec only when the resolution was refused keeps the uncompressed
    path whenever it is available.

    Cameras also substitute a nearby mode without saying so, hence reading
    the values back rather than assuming the request was honoured.
    """
    def apply():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        return (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

    got = apply()
    if got != (width, height):
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        got = apply()
    return got


def _perception_worker_process(engine_name, lang, ocr_votes, in_queue, out_queue):
    """Runs the perception engine in a child process, model kept warm.

    Same process-isolation reason as the legacy worker below: OCR holds
    the GIL for seconds at a time and would freeze the window.

    Only the acquisition stage is rebuilt per frame. Everything after it
    is constructed once and reused, because the extraction stage owns the
    loaded OCR model -- rebuilding the pipeline wholesale would reload it
    on every capture and add seconds to each one.

    `ocr_votes` > 1 needs more than the single settled frame acquisition
    used to get -- see `BiosOcrApp`'s frame buffer, which now hands this
    worker the whole run of frames the stability check already watched
    settle, not just the last one. See
    docs/specs/f-specs/corroboracao-ocr-multi-frame.md for what voting
    buys and what it costs (measured live: ~2x the read time per capture).
    """
    from perception.model import Perception
    from perception.pipeline import run_pipeline
    from perception.stages import (
        Acquisition, Characterisation, Conditioning, Equivalence, Extraction,
        Grouping, Identity, Regionalisation, Serialisation, StateInference,
        Typing,
    )

    warm = [
        Conditioning(),
        Extraction(engine=engine_name, ocr_votes=ocr_votes),
        Characterisation(),
        Regionalisation(),
        Grouping(),
        Equivalence(),
        StateInference(),
        Typing(),
        Identity(),
        Serialisation(view="full"),
    ]

    while True:
        item = in_queue.get()
        if item is None:
            break
        frames, auto = item

        captured_at = time.strftime("%Y%m%d-%H%M%S")
        try:
            stages = [Acquisition(frames=frames, captured_at=captured_at)] + warm
            result = run_pipeline(stages)
        except Exception:                                     # noqa: BLE001
            # A crash here used to kill the worker outright. The queue
            # then had no consumer, the UI waited forever with its busy
            # flag still set, and every later capture -- automatic or from
            # the button -- silently went nowhere. Reporting the failure
            # and staying alive turns a dead app into one bad capture.
            import traceback

            out_queue.put((
                {
                    "mode": "perception",
                    "error": traceback.format_exc(),
                    "captured_at": captured_at,
                },
                None,
                auto,
            ))
            continue
        perception = result.perception

        # Flatten to plain data before crossing the process boundary: the
        # model objects hold numpy arrays and the surface image, none of
        # which needs to be pickled back to the UI.
        states = {s.element_id: s for s in perception.states}
        lines = []
        for primitive in sorted(
            (p for p in perception.primitives if p.is_symbolic and p.content),
            key=lambda p: (p.geometry.y, p.geometry.x),
        ):
            state = states.get(primitive.id)
            klass = perception.klass(state.class_id) if state else None
            group = perception.group(klass.group_id) if klass else None
            typing = perception.type_of(group.id) if group else None
            lines.append({
                "text": primitive.content,
                "state": state.name if state else None,
                "confidence": round(state.confidence, 3) if state else None,
                "channels": list(state.channels) if state else [],
                "hint": typing.semantic_hint if typing else None,
            })

        out_queue.put((
            {
                "mode": "perception",
                "captured_at": captured_at,
                "contract": result.contract,
                "lines": lines,
                "counts": {
                    "primitives": len(perception.primitives),
                    "regions": len(perception.regions),
                    "groups": len(perception.groups),
                    "classes": len(perception.classes),
                    "states": len(perception.states),
                },
                "abstentions": [a.as_dict() for a in perception.abstentions],
                "screen_id": perception.identity.screen_id if perception.identity else None,
                "surface": {
                    "width": perception.surface.width if perception.surface else 0,
                    "height": perception.surface.height if perception.surface else 0,
                    "rectified": perception.surface.rectified if perception.surface else False,
                },
            },
            # The frame the UI shows and `sender.py` saves beside the JSON:
            # the representative one, matching what E1 actually read and
            # what the contract's geometry refers to. The other frames of
            # the burst only ever corroborated content.
            frames[-1],
            auto,
        ))


def _ocr_worker_process(engine_name, lang, extract_cfg, in_queue, out_queue):
    """Runs in a child process: load the model once, then wait for frames.

    Field extraction (the LLM call) also happens here, not on the main
    thread -- it's a multi-second network call, same freeze risk OCR had.

    The legacy path has no vote to spend: `selection.py` reasons about a
    single frame's colours, so this only ever reads the most recent one
    even though the queue item now carries the same settled run of frames
    the perception worker uses for corroboration.
    """
    from ocr import create_ocr_engine

    from selection import annotate_selection

    engine = create_ocr_engine(engine_name, lang=lang)
    while True:
        item = in_queue.get()
        if item is None:  # sentinel: shut down
            break
        frames, auto = item
        frame = frames[-1]
        result = engine.read(frame)
        result["captured_at"] = time.strftime("%Y%m%d-%H%M%S")
        result["screen_bg_color"] = annotate_selection(frame, result["blocks"])

        if extract_cfg is not None:
            from extract import extract_fields

            try:
                fields, unverified = extract_fields(result, **extract_cfg)
                result["fields"] = fields
                result["fields_unverified"] = unverified
            except ExtractionError as e:
                result["fields"] = None
                result["fields_unverified"] = None
                result["fields_error"] = str(e)

        out_queue.put((result, frame, auto))


class BiosOcrApp:
    def __init__(self, root, camera_source=0, stable_threshold=8.0,
                 stable_frames_required=6, change_threshold=10.0,
                 min_ocr_interval=5.0, engine=DEFAULT_ENGINE, lang=None,
                 extract_cfg=None, mode="perception",
                 resolution=(REQUESTED_WIDTH, REQUESTED_HEIGHT),
                 ocr_votes=1):
        self.root = root
        self.mode = mode
        self.resolution = resolution
        self.root.title(
            "BIOS - perception engine (live)" if mode == "perception"
            else "BIOS OCR - live preview"
        )

        self.stable_threshold = stable_threshold
        self.stable_frames_required = stable_frames_required
        self.change_threshold = change_threshold
        self.min_ocr_interval = min_ocr_interval
        self.last_ocr_at = 0.0
        # Every frame the stability check watches settle, kept around so a
        # trigger can hand the worker that whole run instead of just the
        # last frame -- the stability loop already paid for these frames;
        # voting just stops throwing them away. Sized to cover whichever
        # is larger: the settle window itself, or what ocr_votes asks for.
        self.recent_frames = collections.deque(maxlen=max(stable_frames_required, ocr_votes, 1))

        self.in_queue = mp.Queue()
        self.out_queue = mp.Queue()
        if mode == "perception":
            target, args = (
                _perception_worker_process,
                (engine, lang, ocr_votes, self.in_queue, self.out_queue),
            )
        else:
            target, args = (
                _ocr_worker_process,
                (engine, lang, extract_cfg, self.in_queue, self.out_queue),
            )
        self.worker = mp.Process(target=target, args=args, daemon=True)
        self.worker.start()

        self.cap = None
        self.read_failures = 0
        self.camera_connect_queue = queue.Queue()
        self.connecting = False
        self.camera_list_queue = queue.Queue()
        self.refreshing_list = False

        self.prev_gray = None
        self.last_processed_gray = None
        self.stable_count = 0
        self.ocr_busy = False
        self.latest_frame = None

        self._build_layout()
        self.camera_source_var.set(str(camera_source))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(30, self._video_tick)
        self.root.after(200, self._drain_result_queue)
        self.root.after(200, self._poll_camera_connect)
        self.root.after(200, self._poll_camera_list)
        self._refresh_camera_list()
        self._connect_camera()

    def _build_layout(self):
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        camera_row = ttk.Frame(left)
        camera_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(camera_row, text="Camera:").pack(side=tk.LEFT)
        self.camera_source_var = tk.StringVar(value="0")
        # Editable combobox: pick a detected device from the dropdown, or
        # type a custom value (e.g. a phone stream URL) that Refresh won't
        # find on its own since it only probes local webcam indices.
        self.camera_combo = ttk.Combobox(camera_row, textvariable=self.camera_source_var)
        self.camera_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))
        self.refresh_button = ttk.Button(camera_row, text="Refresh", command=self._refresh_camera_list)
        self.refresh_button.pack(side=tk.LEFT, padx=(0, 4))
        self.connect_button = ttk.Button(camera_row, text="Connect", command=self._connect_camera)
        self.connect_button.pack(side=tk.LEFT)

        self.video_label = ttk.Label(
            left, anchor=tk.CENTER, justify=tk.CENTER, text="no camera connected"
        )
        self.video_label.pack(fill=tk.BOTH, expand=True)
        self.status_var = tk.StringVar(value="waiting for a stable screen...")
        ttk.Label(left, textvariable=self.status_var).pack(fill=tk.X, pady=(4, 0))
        ttk.Button(left, text="OCR now", command=self._force_ocr).pack(fill=tk.X, pady=(4, 0))

        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(right, text="OCR result").pack(anchor=tk.W)
        self.text_widget = tk.Text(right, wrap=tk.WORD, width=50)
        self.text_widget.pack(fill=tk.BOTH, expand=True)

    def _refresh_camera_list(self):
        if self.refreshing_list:
            return
        self.refreshing_list = True
        self.refresh_button.state(["disabled"])
        threading.Thread(target=self._camera_list_worker, daemon=True).start()

    def _camera_list_worker(self):
        devices = list_camera_devices()
        self.camera_list_queue.put(devices)

    def _poll_camera_list(self):
        try:
            while True:
                devices = self.camera_list_queue.get_nowait()
                self.refreshing_list = False
                self.refresh_button.state(["!disabled"])
                self.camera_combo["values"] = devices
                if not devices:
                    self.status_var.set(
                        "no local webcam detected -- type a stream URL above (e.g. a phone camera app)"
                    )
        except queue.Empty:
            pass
        self.root.after(500, self._poll_camera_list)

    def _connect_camera(self):
        if self.connecting:
            return
        source = self.camera_source_var.get().strip()
        if not source:
            self.status_var.set("enter a camera index or stream URL first")
            return

        self.connecting = True
        self.connect_button.state(["disabled"])
        self.status_var.set(f"connecting to camera {source!r}...")
        threading.Thread(target=self._connect_worker, args=(source,), daemon=True).start()

    def _connect_worker(self, source):
        resolved = resolve_camera_source(source)
        cap = cv2.VideoCapture(resolved)
        if not cap.isOpened():
            cap.release()
            self.camera_connect_queue.put((None, source, None))
        else:
            self.camera_connect_queue.put(
                (cap, source, request_resolution(cap, *self.resolution))
            )

    def _poll_camera_connect(self):
        try:
            while True:
                cap, source, resolution = self.camera_connect_queue.get_nowait()
                self.connecting = False
                self.connect_button.state(["!disabled"])
                if cap is None:
                    self.status_var.set(f"no camera available at {source!r} -- check the source and try again")
                    self.video_label.configure(image="", text="no camera available")
                    self.video_label.image = None
                else:
                    if self.cap is not None:
                        self.cap.release()
                    self.cap = cap
                    width, height = resolution
                    warning = "  -- too coarse for BIOS text!" if width < 1280 else ""
                    self.status_var.set(
                        f"connected to {source!r} at {width}x{height}{warning}"
                        f" -- waiting for a stable screen..."
                    )
        except queue.Empty:
            pass
        self.root.after(200, self._poll_camera_connect)

    def _video_tick(self):
        if self.cap is not None:
            ok, frame = self.cap.read()
            if ok:
                self.read_failures = 0
                self.latest_frame = frame
                self.recent_frames.append(frame)
                self._render_frame(frame)
                self._check_stability(frame)
            else:
                self._on_read_failure()
        self.root.after(30, self._video_tick)

    def _on_read_failure(self):
        """Give up on a camera that has stopped delivering frames.

        A USB camera can be invalidated mid-session -- unplugged, claimed
        by another process, or driven into a bad state by repeated abrupt
        shutdowns. The read then fails every time, and polling it 33 times
        a second produces thousands of identical backend warnings while
        the window still shows the last good frame, so it looks like the
        app is fine and the screen simply stopped changing.

        Releasing after a short run of failures turns that into a visible,
        actionable state. The threshold is not zero because an occasional
        dropped frame is normal and not worth disconnecting over.
        """
        self.read_failures += 1
        if self.read_failures < MAX_CONSECUTIVE_READ_FAILURES:
            return

        self.cap.release()
        self.cap = None
        self.read_failures = 0
        self.latest_frame = None
        self.video_label.configure(image="", text="camera stopped delivering frames")
        self.video_label.image = None
        self.status_var.set(
            "camera lost -- unplug and replug the USB cable, then press Connect"
        )

    def _render_frame(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        img.thumbnail((640, 480))
        photo = ImageTk.PhotoImage(img)
        self.video_label.configure(image=photo, text="")
        self.video_label.image = photo  # keep a reference, tkinter drops it otherwise

    def _check_stability(self, frame):
        if self.ocr_busy:
            return
        if time.time() - self.last_ocr_at < self.min_ocr_interval:
            # Without a cooldown, a "static" scene whose only variation is
            # per-frame JPEG/sensor noise can keep crossing change_threshold
            # forever, re-triggering PaddleOCR back-to-back and pinning the
            # CPU (observed: one worker process racked up 2700+ CPU-seconds
            # pointed at a near-static frame) instead of settling down.
            return

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self.prev_gray is not None:
            score = float(cv2.absdiff(self.prev_gray, gray).mean())
            self.stable_count = self.stable_count + 1 if score < self.stable_threshold else 0

            if self.stable_count >= self.stable_frames_required:
                is_new_screen = (
                    self.last_processed_gray is None
                    or float(cv2.absdiff(self.last_processed_gray, gray).mean()) > self.change_threshold
                )
                if is_new_screen:
                    self.last_processed_gray = gray.copy()
                    # The settled run itself, not just its last frame --
                    # this is what actually feeds ocr_votes>1 corroboration.
                    self._run_ocr_async(list(self.recent_frames), auto=True)
                self.stable_count = 0

        self.prev_gray = gray

    def _force_ocr(self):
        if self.latest_frame is None:
            self.status_var.set("no frame yet -- connect a camera first")
            return
        if not self.worker.is_alive():
            self.status_var.set("processing worker is not running -- restart the app")
            return
        if self.ocr_busy:
            # Queueing a second capture on top of a running one just makes
            # the operator wait twice; say so instead of silently piling up.
            self.status_var.set("already processing -- wait for the current capture")
            return
        # Manual trigger doesn't wait for the stability check, so whatever
        # is in the buffer is whatever happened to be seen recently -- not
        # guaranteed settled the way the automatic path's burst is.
        self._run_ocr_async(list(self.recent_frames) or [self.latest_frame], auto=False)

    def _run_ocr_async(self, frames, auto):
        self.ocr_busy = True
        self.last_ocr_at = time.time()
        reason = "stable screen detected" if auto else "manual trigger"
        self.status_var.set(f"{reason}, running OCR (can take a few seconds)...")
        self.in_queue.put((frames, auto))

    def _drain_result_queue(self):
        try:
            while True:
                result, frame, auto = self.out_queue.get_nowait()
                self._on_ocr_done(result, frame, auto)
        except queue.Empty:
            pass

        # A worker that dies takes the queue's only consumer with it. The
        # UI would otherwise sit at "running OCR..." forever, with its
        # busy flag stuck, ignoring the button and every later capture --
        # looking like the OCR is merely slow.
        if not self.worker.is_alive():
            self.ocr_busy = False
            self.status_var.set(
                f"processing stopped (worker exited, code "
                f"{self.worker.exitcode}) -- restart the app"
            )

        self.root.after(200, self._drain_result_queue)

    def _on_ocr_done(self, result, frame, auto):
        if result.get("mode") == "perception":
            self._on_perception_done(result, frame, auto)
            return
        send_result(result, image=frame, tag="auto" if auto else "manual")
        self.text_widget.delete("1.0", tk.END)
        self.text_widget.insert(tk.END, result["full_text"])

        highlighted_lines = [
            line
            for block in result["blocks"]
            for line in block["lines"]
            if line.get("highlighted")
        ]
        if highlighted_lines:
            self.text_widget.insert(tk.END, "\n\n--- Highlighted/selected ---\n")
            for line in highlighted_lines:
                self.text_widget.insert(tk.END, f"[{line.get('region')}] {line['text']}\n")

        if "fields" in result:
            self.text_widget.insert(tk.END, "\n\n--- Extracted fields ---\n")
            if result["fields"]:
                for label, value in result["fields"].items():
                    self.text_widget.insert(tk.END, f"{label}: {value}\n")
            if result.get("fields_unverified"):
                self.text_widget.insert(tk.END, "\n(rejected -- value not found verbatim in OCR text)\n")
                for label, value in result["fields_unverified"].items():
                    self.text_widget.insert(tk.END, f"{label}: {value}\n")
            if result.get("fields_error"):
                self.text_widget.insert(tk.END, f"\n(extraction failed: {result['fields_error']})\n")

        word_count = sum(len(l["words"]) for b in result["blocks"] for l in b["lines"])
        self.status_var.set(f"last OCR at {result['captured_at']} - {word_count} words")
        self.ocr_busy = False

    def _on_perception_done(self, result, frame, auto):
        if result.get("error"):
            self.text_widget.delete("1.0", tk.END)
            self.text_widget.insert(tk.END, "--- capture failed ---\n\n")
            self.text_widget.insert(tk.END, result["error"])
            self.status_var.set("capture failed -- details in the panel")
            self.ocr_busy = False
            return

        try:
            send_result(
                {"captured_at": result["captured_at"], **result["contract"]},
                image=frame,
                tag="auto" if auto else "manual",
            )
        except Exception as exc:                              # noqa: BLE001
            # Saving is a side errand; failing it must not cost the
            # operator the reading they just waited for.
            self.status_var.set(f"(could not save capture: {exc})")

        counts = result["counts"]
        surface = result["surface"]
        text = self.text_widget
        text.delete("1.0", tk.END)

        text.insert(tk.END, "--- text read ---\n")
        if result["lines"]:
            for line in result["lines"]:
                mark = ""
                if line["state"]:
                    mark = (
                        f"   <<< {line['state'].upper()}"
                        f" ({line['confidence']:.2f}"
                        f", {','.join(line['channels'])})"
                    )
                    if line["hint"]:
                        mark += f" [{line['hint']}]"
                text.insert(tk.END, f"{line['text']}{mark}\n")
        else:
            text.insert(
                tk.END,
                "(nothing read -- fill the frame with the screen, check focus)\n",
            )

        states = [line for line in result["lines"] if line["state"]]
        text.insert(tk.END, f"\n--- states ({len(states)}) ---\n")
        for line in states:
            text.insert(
                tk.END,
                f"{line['state']}: {line['text']}  "
                f"conf={line['confidence']:.2f} [{line['hint']}]\n",
            )
        if not states:
            text.insert(tk.END, "none detected\n")

        # Abstentions are shown, not hidden: "could not tell" and "nothing
        # is selected" are different answers and the operator needs to see
        # which one this is.
        if result["abstentions"]:
            counted = {}
            for abstention in result["abstentions"]:
                key = f"{abstention['stage']} {abstention['reason']}"
                counted[key] = counted.get(key, 0) + 1
            text.insert(tk.END, f"\n--- did not decide ({len(result['abstentions'])}) ---\n")
            for key in sorted(counted):
                text.insert(tk.END, f"{counted[key]}x {key}\n")

        text.insert(
            tk.END,
            f"\n--- objects ---\n"
            f"{counts['primitives']} primitives, {counts['regions']} regions, "
            f"{counts['groups']} groups, {counts['classes']} classes\n"
            f"screen_id {result['screen_id']}\n",
        )

        self.status_var.set(
            f"{result['captured_at']} - {surface['width']}x{surface['height']} - "
            f"{counts['primitives']} read, {counts['states']} state(s)"
        )
        self.ocr_busy = False

    def _on_close(self):
        if self.cap is not None:
            self.cap.release()
        self.in_queue.put(None)
        self.worker.terminate()
        self.root.destroy()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="BIOS OCR live GUI")
    parser.add_argument("--camera-source", default="0",
                         help="Webcam index (e.g. 0) or a stream URL (e.g. http://<ip>:8080/video)")
    parser.add_argument("--engine", choices=ENGINE_CHOICES, default=DEFAULT_ENGINE,
                         help="OCR engine (see study_ocr_engines.py for a measured "
                              "speed comparison on this machine)")
    parser.add_argument("--lang", default=None, help="Language code (engine-specific default if omitted)")
    parser.add_argument("--stable-threshold", type=float, default=8.0)
    parser.add_argument("--stable-frames", type=int, default=6)
    parser.add_argument("--change-threshold", type=float, default=10.0)
    parser.add_argument("--min-ocr-interval", type=float, default=5.0,
                         help="Minimum seconds between automatic OCR triggers")
    parser.add_argument("--ocr-votes", type=int, default=3,
                         help="Perception path only: re-read each detected text "
                              "box from up to N-1 extra frames of the same "
                              "settled screen and vote on content (1 = single "
                              "read). Default 3 is the measured sweet spot -- "
                              "see docs/studies/estudo-votacao-ocr-multi-frame.md: "
                              "eliminated the corroborable errors in a live "
                              "10-round test (5 was no better and slower), at "
                              "~2x the read time per capture.")
    parser.add_argument("--resolution", default=f"{REQUESTED_WIDTH}x{REQUESTED_HEIGHT}",
                         help="Resolution to request from the camera, WxH. Higher is "
                              "not automatically better: a camera's top mode is often "
                              "interpolated and softer than its native one. Measure "
                              "before raising this.")
    parser.add_argument("--legacy", action="store_true",
                         help="Use the original OCR + selection.py path instead of "
                              "the perception engine. Kept because the two are not "
                              "yet equivalent: the engine is better on the vertical-"
                              "sidebar BIOS and worse on AMI body items -- see the "
                              "measurements in ESTUDO_SELECAO.md and the specs.")
    parser.add_argument("--extract-fields", action="store_true",
                         help="Legacy path only: run OCR text through the local LLM "
                              "(Lemonade/FastFlowLM) to extract label->value fields")
    parser.add_argument("--llm-host", default=DEFAULT_HOST)
    parser.add_argument("--llm-port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--llm-model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    try:
        resolution = tuple(int(v) for v in args.resolution.lower().split("x"))
        if len(resolution) != 2:
            raise ValueError
    except ValueError:
        parser.error(f"--resolution must look like 1280x720, got {args.resolution!r}")

    extract_cfg = None
    if args.extract_fields:
        if not args.legacy:
            parser.error(
                "--extract-fields belongs to the legacy path; add --legacy to use it. "
                "Field extraction is a cognition step and sits after perception, "
                "not inside it."
            )
        extract_cfg = {"host": args.llm_host, "port": args.llm_port, "model": args.llm_model}

    root = tk.Tk()
    BiosOcrApp(
        root,
        camera_source=args.camera_source,
        stable_threshold=args.stable_threshold,
        stable_frames_required=args.stable_frames,
        change_threshold=args.change_threshold,
        min_ocr_interval=args.min_ocr_interval,
        engine=args.engine,
        lang=args.lang,
        extract_cfg=extract_cfg,
        mode="legacy" if args.legacy else "perception",
        resolution=resolution,
        ocr_votes=args.ocr_votes,
    )
    root.mainloop()


if __name__ == "__main__":
    mp.freeze_support()
    main()
