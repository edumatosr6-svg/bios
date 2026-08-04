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
import multiprocessing as mp
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import cv2
from PIL import Image, ImageTk

from capture import list_camera_devices, resolve_camera_source
from extract import DEFAULT_HOST, DEFAULT_MODEL, DEFAULT_PORT, ExtractionError
from sender import send_result


def _ocr_worker_process(engine_name, lang, extract_cfg, in_queue, out_queue):
    """Runs in a child process: load the model once, then wait for frames.

    Field extraction (the LLM call) also happens here, not on the main
    thread -- it's a multi-second network call, same freeze risk OCR had.
    """
    from ocr import create_ocr_engine

    from selection import annotate_selection

    engine = create_ocr_engine(engine_name, lang=lang)
    while True:
        item = in_queue.get()
        if item is None:  # sentinel: shut down
            break
        frame, auto = item
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
                 min_ocr_interval=5.0, engine="paddleocr", lang=None,
                 extract_cfg=None):
        self.root = root
        self.root.title("BIOS OCR - live preview")

        self.stable_threshold = stable_threshold
        self.stable_frames_required = stable_frames_required
        self.change_threshold = change_threshold
        self.min_ocr_interval = min_ocr_interval
        self.last_ocr_at = 0.0

        self.in_queue = mp.Queue()
        self.out_queue = mp.Queue()
        self.worker = mp.Process(
            target=_ocr_worker_process,
            args=(engine, lang, extract_cfg, self.in_queue, self.out_queue),
            daemon=True,
        )
        self.worker.start()

        self.cap = None
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
            self.camera_connect_queue.put((None, source))
        else:
            self.camera_connect_queue.put((cap, source))

    def _poll_camera_connect(self):
        try:
            while True:
                cap, source = self.camera_connect_queue.get_nowait()
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
                    self.status_var.set(f"connected to {source!r}, waiting for a stable screen...")
        except queue.Empty:
            pass
        self.root.after(200, self._poll_camera_connect)

    def _video_tick(self):
        if self.cap is not None:
            ok, frame = self.cap.read()
            if ok:
                self.latest_frame = frame
                self._render_frame(frame)
                self._check_stability(frame)
        self.root.after(30, self._video_tick)

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
                    self._run_ocr_async(frame, auto=True)
                self.stable_count = 0

        self.prev_gray = gray

    def _force_ocr(self):
        if self.latest_frame is not None:
            self._run_ocr_async(self.latest_frame, auto=False)

    def _run_ocr_async(self, frame, auto):
        self.ocr_busy = True
        self.last_ocr_at = time.time()
        reason = "stable screen detected" if auto else "manual trigger"
        self.status_var.set(f"{reason}, running OCR (can take a few seconds)...")
        self.in_queue.put((frame, auto))

    def _drain_result_queue(self):
        try:
            while True:
                result, frame, auto = self.out_queue.get_nowait()
                self._on_ocr_done(result, frame, auto)
        except queue.Empty:
            pass
        self.root.after(200, self._drain_result_queue)

    def _on_ocr_done(self, result, frame, auto):
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
    parser.add_argument("--engine", choices=["tesseract", "paddleocr"], default="paddleocr")
    parser.add_argument("--lang", default=None, help="Language code (engine-specific default if omitted)")
    parser.add_argument("--stable-threshold", type=float, default=8.0)
    parser.add_argument("--stable-frames", type=int, default=6)
    parser.add_argument("--change-threshold", type=float, default=10.0)
    parser.add_argument("--min-ocr-interval", type=float, default=5.0,
                         help="Minimum seconds between automatic OCR triggers")
    parser.add_argument("--extract-fields", action="store_true",
                         help="Also run OCR text through the local LLM (Lemonade/FastFlowLM) to extract label->value fields")
    parser.add_argument("--llm-host", default=DEFAULT_HOST)
    parser.add_argument("--llm-port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--llm-model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    extract_cfg = None
    if args.extract_fields:
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
    )
    root.mainloop()


if __name__ == "__main__":
    mp.freeze_support()
    main()
