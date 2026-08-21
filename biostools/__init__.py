"""Named tools that answer questions about a BIOS screen.

A tool navigates the machine under test with the USB-KM232 cable
(`actuator.py`), reads the screen back through the perception engine
(`perception/`), and returns a structured answer. Reading and acting are
paired on purpose: every keypress is verified against what the screen
actually shows afterwards, never assumed.

    from biostools import BiosSession, run_tool

    with BiosSession(camera_source=0, serial_port="COM3") as session:
        print(run_tool("cpu_temperature", session).as_text())

One session serves many tools, so a tool may call another without paying
the OCR model load again -- see `session.py`.

CLI:  py -3.13 -m biostools cpu-temperature --serial-port COM3
"""
from .registry import (
    AllFields, Entries, Field, Fields, Step, Tool, ToolResult, UnknownTool,
    register,
)
from .registry import all_tools as _all_tools
from .registry import get as _get
from .session import BiosSession, CameraUnavailable, Reading

__all__ = [
    "BiosSession", "CameraUnavailable", "Reading",
    "Tool", "Step", "ToolResult", "UnknownTool",
    "Field", "Fields", "AllFields", "Entries",
    "register", "get", "all_tools", "list_tools", "run_tool",
]


def _load():
    """Import the tool definitions so they register themselves.

    Deferred rather than done at import time so that `import biostools`
    costs nothing -- listing tools must not drag in the perception engine
    or an OCR model.
    """
    from . import tools  # noqa: F401


def get(name):
    """One tool by name, loading the definitions first.

    Wraps `registry.get`, which on its own would raise "unknown tool" with
    an empty list whenever the caller had not happened to import
    `biostools.tools` -- a confusing failure that says the tool does not
    exist when it simply had not been registered yet.
    """
    _load()
    return _get(name)


def all_tools():
    _load()
    return _all_tools()


def list_tools():
    """{name: question} for every registered tool."""
    return {name: tool.question for name, tool in sorted(all_tools().items())}


def run_tool(name, session):
    """Run one tool against an already-open session."""
    return get(name).run(session)
