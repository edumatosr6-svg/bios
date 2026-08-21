"""Image acquisition: from a live camera or from a test file on disk."""
import sys

import cv2


def open_camera(source):
    """Open a camera device, preferring the backend that does not stall.

    On Windows OpenCV defaults to MSMF, whose cold start on this hardware
    was measured at **25-27 seconds** for a single device -- and
    `list_camera_devices` pays it once per probed index. DirectShow opens
    the same device in **0.2s** and, measured on the HDMI capture card at
    1280x720, returns a *sharper* frame (Laplacian variance 654 vs 535).
    Faster and better, so there is no trade-off to weigh here.

    Only device indices get the backend hint: a URL source (an MJPEG
    stream) is handled by a different backend entirely, and passing
    CAP_DSHOW with one just fails. If DirectShow cannot open the device
    -- some virtual cameras are MSMF-only -- the plain call is retried, so
    the worst case is the old behaviour rather than a failure.
    """
    if isinstance(source, int) and sys.platform == "win32":
        cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
        if cap.isOpened():
            return cap
        cap.release()
    return cv2.VideoCapture(source)


def resolve_camera_source(value):
    """Camera source can be a numeric device index (webcam), a URL (e.g.
    an IP Webcam MJPEG stream like http://<phone-ip>:8080/video), or a
    "<index>: <device name>" label as shown by list_camera_devices() --
    only the index before the colon matters for actually opening it.
    """
    if isinstance(value, int):
        return value
    value = value.strip()
    head = value.split(":", 1)[0].strip()
    if head.isdigit():
        return int(head)
    return value


def capture_from_camera(camera_source=0, warmup_frames=5):
    """Grab one frame from a camera. Discards a few initial frames
    so auto-exposure/auto-focus can settle before the real capture.
    """
    camera_source = resolve_camera_source(camera_source)
    cap = open_camera(camera_source)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera source {camera_source}")

    try:
        frame = None
        for _ in range(warmup_frames):
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("Failed to read frame from camera")
        return frame
    finally:
        cap.release()


def list_camera_devices(max_index=6):
    """Probe local webcam indices 0..max_index-1 and return the ones that
    actually open and deliver a frame, labeled with a Windows device name
    when one can be confidently matched. Doesn't include network/URL
    sources -- those are always typed in directly.
    """
    working = []
    for i in range(max_index):
        cap = open_camera(i)
        if cap.isOpened():
            ok, _ = cap.read()
            if ok:
                working.append(i)
        cap.release()

    names = _windows_camera_names()
    if len(names) != len(working):
        # Can't confidently line up names with indices (extra/missing
        # devices, disabled entries, different enumeration order) --
        # showing a wrong name next to an index is worse than no name.
        names = []

    return [f"{idx}: {name}" if name else str(idx) for idx, name in zip(working, names or [None] * len(working))]


def _windows_camera_names():
    import subprocess

    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                # PNPClass 'Camera' only. 'Image' also matches scanners and
                # multifunction printers, which never appear as OpenCV
                # camera indices -- one networked scanner in the list was
                # enough to make the count mismatch below discard every
                # name, so the listing showed bare indices with no way to
                # tell the webcam from the built-in one.
                "Get-CimInstance Win32_PnPEntity | "
                "Where-Object { $_.PNPClass -eq 'Camera' } | "
                "Select-Object -ExpandProperty Name",
            ],
            capture_output=True, text=True, timeout=5,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def load_from_file(path):
    frame = cv2.imread(path)
    if frame is None:
        raise RuntimeError(f"Could not load image: {path}")
    return frame
