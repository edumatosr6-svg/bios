"""CLI: run one tool by name, or ask a free-text question, and print the answer.

    py -3.13 -m biostools --list
    py -3.13 -m biostools cpu-temperature --serial-port COM3
    py -3.13 -m biostools cpu-temperature --serial-port COM3 --text
    py -3.13 -m biostools --ask "qual a temperatura da cpu?" --serial-port COM3 --text

JSON by default because the caller today may be a script or another tool;
`--text` is for an operator reading it directly. Exit status is 1 when no
answer was produced, so a shell script can branch on it.

`--ask` goes through `assistant.ask()`: an LLM call picks the tool, the
tool runs exactly as it would from the CLI directly, and a second LLM
call phrases the result -- verified to contain the tool's value verbatim
before being shown (see assistant.py's docstring for why that second
call is the dangerous one). Needs --llm-host/--llm-port reachable; the
CLI's own resolution/frames/engine flags apply to whichever tool gets
picked, same as if it had been named directly.
"""
import argparse
import json
import logging
import os
import signal
import sys
import warnings

# Silence engine start-up chatter before anything imports them. An
# operator asking one question should not get a wall of unrelated text
# (a urllib3/chardet version warning from `requests`, model-loading
# notices from the OCR engine). Scoped to the CLI on purpose -- a library
# caller keeps whatever logging it configured.
#
# Only warnings and info-level logging are muted. Real errors still print,
# and a failure still exits non-zero, so nothing that matters gets hidden.
warnings.filterwarnings("ignore")
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")
for _noisy in ("rapidocr", "onnxruntime", "openvino"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

from actuator import CableNotResponding, list_serial_ports
from extract import DEFAULT_HOST, DEFAULT_MODEL, DEFAULT_PORT
from ocr import DEFAULT_ENGINE, ENGINE_CHOICES

from . import BiosSession, list_tools
from . import get as _get
from . import _load
from .registry import UnknownTool
from .session import ActuatorUnavailable, CameraUnavailable


def get_tool(name):
    _load()
    return _get(name)


def parse_args():
    parser = argparse.ArgumentParser(
        prog="biostools",
        description="Ask the BIOS a question: navigate to the right screen and read the answer.",
    )
    parser.add_argument("tool", nargs="?",
                        help="Tool name, e.g. cpu-temperature (see --list)")
    parser.add_argument("--list", action="store_true",
                        help="List available tools and exit")
    parser.add_argument("--ask",
                        help="Free-text question instead of a tool name -- an LLM "
                             "picks the tool and phrases the answer. See --llm-*.")
    parser.add_argument("--llm-host", default=DEFAULT_HOST)
    parser.add_argument("--llm-port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--llm-model", default=DEFAULT_MODEL)
    parser.add_argument("--camera-source", default="0",
                        help="Camera index or stream URL showing the BIOS screen")
    parser.add_argument("--serial-port",
                        help="COM port of the USB-KM232 cable, e.g. COM3. Required "
                             "for any tool whose route needs to move the cursor.")
    parser.add_argument("--engine", choices=ENGINE_CHOICES, default=DEFAULT_ENGINE)
    parser.add_argument("--resolution", default="1280x720")
    parser.add_argument("--frames", type=int, default=1,
                        help="Frames per reading; >1 enables OCR corroboration")
    parser.add_argument("--ocr-votes", type=int, default=1,
                        help="Vote OCR content across frames (needs --frames >= this). "
                             "Reads better but roughly doubles time per reading.")
    parser.add_argument("--text", action="store_true",
                        help="Human-readable output instead of JSON")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.list or not (args.tool or args.ask):
        for name, question in list_tools().items():
            print(f"  {name.replace('_', '-'):24s} {question}")
        return 0 if args.list else 1

    try:
        resolution = tuple(int(v) for v in args.resolution.lower().split("x"))
        if len(resolution) != 2:
            raise ValueError
    except ValueError:
        sys.exit(f"--resolution must look like 1280x720, got {args.resolution!r}")

    # `--ask` does not know which tool it needs until the LLM routes it, so
    # the "route needs the cable" check below only applies to a tool named
    # directly. An --ask session opens without a cable and simply fails
    # later, through the same ActuatorUnavailable handling, if the tool it
    # picked turns out to need one.
    tool = None
    if args.tool:
        # Resolved before touching hardware, so an unknown name fails
        # instantly instead of after the camera opens and a model loads.
        try:
            tool = get_tool(args.tool)
        except UnknownTool as e:
            sys.exit(str(e))

        if tool.route and not args.serial_port:
            sys.exit(
                f"{args.tool} has to move the cursor to reach its screen, so it needs "
                f"the USB-KM232 cable: pass --serial-port (e.g. --serial-port COM3). "
                f"Available ports: "
                + (", ".join(f"{dev} ({desc})" for dev, desc in list_serial_ports())
                   or "none detected")
            )

    session = None

    # An abrupt kill does not run `finally`, and on Windows that leaves the
    # camera locked open for the next process -- the same trap watcher.py
    # hit. Handled here rather than in BiosSession: grabbing process-wide
    # signals is the entry point's call to make, not a library's.
    def _release(signum, frame):
        if session is not None:
            session.close()
        sys.exit(130)

    signal.signal(signal.SIGINT, _release)
    signal.signal(signal.SIGTERM, _release)

    try:
        session = BiosSession(
            camera_source=args.camera_source,
            serial_port=args.serial_port,
            engine=args.engine,
            resolution=resolution,
            frames=args.frames,
            ocr_votes=args.ocr_votes,
        )
        with session:
            if args.ask:
                from . import assistant

                answer = assistant.ask(
                    args.ask, session,
                    host=args.llm_host, port=args.llm_port, model=args.llm_model,
                )
                print(answer.answer if args.text
                      else json.dumps(answer.as_dict(), indent=2, ensure_ascii=False))
                # A question with zero tool calls (the model declined
                # outright, e.g. "não sei responder isso") is still a
                # valid conversational answer, not a technical failure --
                # only an endpoint error or every call failing counts.
                failed = bool(answer.error) or (
                    answer.calls and not any(c.result and c.result.ok for c in answer.calls)
                )
                return 1 if failed else 0

            result = tool.run(session)
    except CameraUnavailable as e:
        sys.exit(f"camera: {e}")
    except ActuatorUnavailable as e:
        sys.exit(f"cabo: {e}")
    except CableNotResponding as e:
        # The cable stopped ACKing mid-run. Distinct from a BIOS answer we
        # could not read: the link to the machine is broken, and any
        # further keypress would be sent blind.
        sys.exit(f"cabo parou de responder: {e}")

    print(result.as_text() if args.text
          else json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
