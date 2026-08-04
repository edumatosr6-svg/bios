"""Image acquisition: from a live camera or from a test file on disk."""
import cv2


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
    cap = cv2.VideoCapture(camera_source)
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
        cap = cv2.VideoCapture(i)
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
                "Get-CimInstance Win32_PnPEntity | "
                "Where-Object { $_.PNPClass -eq 'Camera' -or $_.PNPClass -eq 'Image' } | "
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
