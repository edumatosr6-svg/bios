"""CLI for the perception engine: run it on a file or a live camera.

    py -3.13 -m perception.run --source file --input captures/positivo_advanced_mapt.jpg
    py -3.13 -m perception.run --source camera --camera-source 0 --frames 5
    py -3.13 -m perception.run --source file --input x.jpg --view full --output x.json

`--frames` on a camera grabs several consecutive frames and hands them to
E0 as one bundle, which is what lets acquisition judge whether the view
has settled instead of trusting a single grab.
"""
import argparse
import json
import os
import sys

# Silence OpenCV's internal probe chatter before it is imported. Scanning
# for cameras opens indices that do not exist, and the backend logs each
# one as an ERROR ("Camera index out of range") even though not finding a
# fifth camera is the expected result. Those lines look like a failure and
# are not one.
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

import cv2

cv2.setLogLevel(0)

from ocr import DEFAULT_ENGINE, ENGINE_CHOICES

from . import describe_pipeline, default_pipeline, perceive


def parse_args():
    parser = argparse.ArgumentParser(description="Interface Perception Engine")
    parser.add_argument("--source", choices=["file", "camera"], default="file")
    parser.add_argument("--input", help="image path (--source file)")
    parser.add_argument("--camera-source", default="0",
                        help="webcam index (e.g. 0) or stream URL")
    parser.add_argument("--frames", type=int, default=1,
                        help="frames to grab from the camera as one bundle")
    parser.add_argument("--warmup", type=int, default=8,
                        help="frames discarded before capture so auto-exposure "
                             "and autofocus can settle (camera only)")
    parser.add_argument("--resolution", default="1280x720",
                        help="resolution to request from the camera, WxH. "
                             "Webcams default to 640x480, too coarse for BIOS "
                             "text -- but a camera's *top* mode is often "
                             "interpolated and softer than its native one, so "
                             "higher is not automatically better. Measure "
                             "before raising it. Use 'native' to skip.")
    parser.add_argument("--list-cameras", action="store_true",
                        help="show which camera indices actually work, then exit")
    parser.add_argument("--save-frame", metavar="PATH",
                        help="also write the captured frame here, to see what "
                             "the engine actually looked at")
    parser.add_argument("--text", action="store_true",
                        help="print the text read from the screen, in reading order")
    parser.add_argument("--engine", choices=ENGINE_CHOICES, default=DEFAULT_ENGINE,
                        help="OCR engine (see study_ocr_engines.py for a measured "
                             "speed comparison on this machine)")
    parser.add_argument("--no-rectify", action="store_true",
                        help="skip screen rectification (E1 identity pass-through)")
    parser.add_argument("--view", choices=["digest", "full", "both"], default="digest")
    parser.add_argument("--output", help="write JSON here instead of stdout")
    parser.add_argument("--trace", action="store_true", help="print per-stage counts")
    parser.add_argument("--summary", action="store_true",
                        help="human-readable summary instead of JSON")
    parser.add_argument("--explain", action="store_true",
                        help="show the decision chain -- regions, groups, classes "
                             "and every channel's per-member measurement -- so a "
                             "wrong answer can be read back to the stage that "
                             "produced it")
    parser.add_argument("--describe", action="store_true",
                        help="print the stage/level table and exit")
    return parser.parse_args()


def load_frames(args) -> list:
    if args.source == "file":
        if not args.input:
            sys.exit("--input is required when --source file")
        image = cv2.imread(args.input)
        if image is None:
            sys.exit(f"could not read {args.input}")
        return [image]

    from capture import resolve_camera_source

    source = resolve_camera_source(args.camera_source)
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        sys.exit(
            f"could not open camera {args.camera_source!r}. "
            f"Try --list-cameras to see which indices work."
        )

    _request_resolution(cap, args.resolution)
    actual = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
              int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    print(f"camera {source}: capturing at {actual[0]}x{actual[1]}")
    if actual[0] < 1280:
        print(
            "  warning: this is low for BIOS text. The camera may not support "
            "more, or may need to be closer to the screen.",
            file=sys.stderr,
        )

    frames = []
    try:
        # Discard the first frames: a webcam opens with auto-exposure and
        # autofocus still settling, and those frames are darker and softer
        # than what the camera will actually deliver. Measuring colour on
        # them would characterise the warm-up, not the screen.
        for _ in range(max(0, args.warmup)):
            cap.read()
        for _ in range(max(1, args.frames)):
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
    finally:
        cap.release()
    if not frames:
        sys.exit("camera opened but returned no frames")
    return frames


def read_text(result) -> str:
    """Everything the engine read, in reading order, with what it concluded."""
    p = result.perception
    lines = ["text read from the screen:"]
    states = {s.element_id: s for s in p.states}
    symbolic = [x for x in p.primitives if x.is_symbolic and x.content]
    for primitive in sorted(symbolic, key=lambda x: (x.geometry.y, x.geometry.x)):
        state = states.get(primitive.id)
        mark = f"  <- {state.name.upper()}" if state else ""
        lines.append(f"  {primitive.content}{mark}")
    if not symbolic:
        lines.append("  (nothing read -- check focus, framing and lighting)")
    return "\n".join(lines)


def _request_resolution(cap, resolution: str) -> None:
    """Ask the camera for a usable resolution before capturing.

    OpenCV opens a webcam at whatever the driver offers by default, which
    is routinely 640x480 -- fine for a video call, far too coarse for BIOS
    menu text. Nothing in the prototype ever set this, so every camera run
    so far has been at the default.

    The plain request comes first and MJPG is only a fallback. Many USB
    webcams need the codec switch to reach their higher modes, but MJPG is
    compressed and its artefacts land on the glyph edges OCR depends on,
    so the uncompressed path is kept whenever it suffices.
    """
    if resolution.lower() == "native":
        return
    try:
        width, height = (int(v) for v in resolution.lower().split("x"))
    except ValueError:
        sys.exit(f"--resolution must look like 1280x720, got {resolution!r}")

    def apply():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        return (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

    if apply() != (width, height):
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        apply()


def summarise(result) -> str:
    p = result.perception
    lines = []
    if p.identity:
        lines.append(f"screen_id : {p.identity.screen_id}")
        lines.append(f"title     : {p.identity.title_text!r}")
    surface = p.surface
    if surface:
        lines.append(
            f"surface   : {surface.width}x{surface.height} "
            f"rectified={surface.rectified} frames={surface.frames_used}"
        )
    lines.append(
        f"objects   : {len(p.primitives)} primitives, {len(p.regions)} regions, "
        f"{len(p.groups)} groups, {len(p.classes)} classes, {len(p.states)} states"
    )

    by_id = p.primitives_by_id()
    if p.states:
        lines.append("")
        lines.append("states:")
        for state in p.states:
            primitive = by_id.get(state.element_id)
            text = (primitive.content if primitive else state.element_id) or ""
            klass = p.klass(state.class_id)
            group = p.group(klass.group_id) if klass else None
            typing = p.type_of(group.id) if group else None
            hint = typing.semantic_hint if typing else None
            lines.append(
                f"  {state.name:<10} {text[:44]:<46} "
                f"conf={state.confidence:.2f} channels={','.join(state.channels)}"
                + (f" [{hint}]" if hint else "")
            )
    else:
        lines.append("")
        lines.append("states: none")

    if p.abstentions:
        lines.append("")
        lines.append(f"abstentions ({len(p.abstentions)}):")
        counted: dict[str, int] = {}
        for a in p.abstentions:
            counted[f"{a.stage} {a.reason}"] = counted.get(f"{a.stage} {a.reason}", 0) + 1
        for key in sorted(counted):
            lines.append(f"  {counted[key]:>3}x {key}")
    return "\n".join(lines)


def main():
    args = parse_args()

    if args.describe:
        print(describe_pipeline(default_pipeline(frames=[None])))
        return

    if args.list_cameras:
        from capture import list_camera_devices

        devices = list_camera_devices()
        print("\n".join(devices) if devices else "no working camera found")
        return

    frames = load_frames(args)

    if args.save_frame:
        cv2.imwrite(args.save_frame, frames[-1])
        print(f"wrote {args.save_frame}")
    result = perceive(
        frames=frames,
        engine=args.engine,
        rectify=not args.no_rectify,
        view=args.view,
        trace=args.trace,
    )

    if args.explain:
        from .explain import explain

        print(explain(result.perception))
        return

    if args.text:
        print(read_text(result))
        if args.summary:
            print()

    if args.summary:
        print(summarise(result))
        return

    if args.text:
        return

    payload = json.dumps(result.contract, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"wrote {args.output}")
    else:
        print(payload)


if __name__ == "__main__":
    main()
