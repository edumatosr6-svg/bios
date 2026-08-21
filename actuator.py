"""Keyboard/mouse control of a BIOS target via a USB-KM232 cable.

The USB-KM232 (Hagstrom Electronics) is a two-ended cable: the USB end
plugs into the target machine and presents itself as a standard USB HID
keyboard/mouse -- no driver needed, and it works inside a BIOS/UEFI screen
since BIOS natively supports USB HID input. The RS-232 end is what we
control: a byte sent over that serial line is translated into a keystroke
or mouse action on the target.

**No configuration step and no config utility for this model** -- unlike
its sibling the USB-ASC232 (which has selectable ASCII/Extended
ASCII/Key Number modes and a "USBASC232.EXE" setup tool), the KM232 has
one fixed protocol permanently: **9600 baud, 8 data bits, no parity, 1
stop bit**, and it always speaks key-number make/break codes -- there is
no ASCII passthrough mode to select. Confirmed against the real cable
2026-08-20: Windows' bus-reported device description read literally
"Hagstrom Electronics, Inc. USBKM232", not ASC232 -- the two products
look identical (same cable, same connectors) but are different firmware,
and USBASC232.EXE will never detect a KM232 (that was the entire cause of
the "No USB-ASC232 device was detected" error hit while trying to use the
wrong utility on this cable). Just open the serial port at 9600/8/N/1 and
start sending bytes -- nothing to install or save to the cable first.

Each key has a one-byte "make" code (press) and "break" code (make +
0x80, i.e. release) -- see KEY_CODES. A make is NOT auto-released, so
every make must be paired with a break later or the key stays "held" on
the target (press()/combo() below always pair them).

**Handshaking is done in-band, not via RTS/CTS.** The KM232 replies to
almost every byte it receives with one response byte: the one's
complement (~byte & 0xFF) of what it was sent. That response is the
signal "I've processed that, send the next one" -- there is no separate
hardware flow-control line for this model. All the write methods here
read and return that response so a caller can detect a desync (response
doesn't match) or a dead/disconnected cable (no response before timeout).
"""
import time

import serial
import serial.tools.list_ports

# US Key Number Table (decimal make codes; break = make + 128). Transcribed
# from the USB-KM232 manual's printed table (page 6) -- an international
# variant is in the same manual's appendix if a non-US layout is ever
# needed. Identical numbering to the USB-ASC232's table (same underlying
# key-number design shared across Hagstrom's cable family).
KEY_CODES = {
    "`": 1, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9,
    "9": 10, "0": 11, "-": 12, "=": 13, "backspace": 15, "tab": 16,
    "q": 17, "w": 18, "e": 19, "r": 20, "t": 21, "y": 22, "u": 23, "i": 24,
    "o": 25, "p": 26, "[": 27, "]": 28, "\\": 29, "capslock": 30,
    "a": 31, "s": 32, "d": 33, "f": 34, "g": 35, "h": 36, "j": 37, "k": 38,
    "l": 39, ";": 40, "'": 41, "enter": 43, "lshift": 44,
    "z": 46, "x": 47, "c": 48, "v": 49, "b": 50, "n": 51, "m": 52,
    ",": 53, ".": 54, "/": 55, "rshift": 57, "lctrl": 58, "lalt": 60,
    "space": 61, "ralt": 62, "rctrl": 64, "lwin": 70, "rwin": 71,
    "winapl": 72, "insert": 75, "delete": 76, "left": 79, "home": 80,
    "end": 81, "up": 83, "down": 84, "pageup": 85, "pagedown": 86,
    "right": 89, "numlock": 90,
    "kp7": 91, "kp4": 92, "kp1": 93, "kp/": 95, "kp8": 96, "kp5": 97,
    "kp2": 98, "kp0": 99, "kp*": 100, "kp9": 101, "kp6": 102, "kp3": 103,
    "kp.": 104, "kp-": 105, "kp+": 106, "kpenter": 108,
    "esc": 110, "f1": 112, "f2": 113, "f3": 114, "f4": 115, "f5": 116,
    "f6": 117, "f7": 118, "f8": 119, "f9": 120, "f10": 121, "f11": 122,
    "f12": 123, "prtscr": 124, "scrolllock": 125, "pause": 126,
}

# Aliases for names people actually type, mapped onto the table above.
_ALIASES = {
    "pgup": "pageup", "pgdn": "pagedown", "pagedn": "pagedown",
    "return": "enter", "del": "delete", "ins": "insert",
    "leftarrow": "left", "rightarrow": "right", "uparrow": "up",
    "downarrow": "down", "shift": "lshift", "ctrl": "lctrl", "alt": "lalt",
    "win": "lwin",
}

# Fixed, non-negotiable serial protocol for this model (see module docstring).
BAUD_RATE = 9600

BUFFER_CLEAR = 0x38
LED_STATUS_QUERY = 0x7F

# Single-byte mouse command codes (a completely different, simpler scheme
# than the USB-ASC232's 4-byte packet protocol -- this model has no
# absolute/relative delta, just discrete step commands).
MOUSE_LEFT = 0x42
MOUSE_RIGHT = 0x43
MOUSE_UP = 0x44
MOUSE_DOWN = 0x45
MOUSE_STEP_SMALL = 0x6D  # default on power-up
MOUSE_STEP_LARGE = 0x6F
SCROLL_UP = 0x57
SCROLL_DOWN = 0x58
BUTTON_LEFT_ON, BUTTON_LEFT_OFF = 0x49, 0xC9
BUTTON_RIGHT_ON, BUTTON_RIGHT_OFF = 0x4A, 0xCA
BUTTON_MIDDLE_ON, BUTTON_MIDDLE_OFF = 0x4D, 0xCD

# Hold time between a make and its break. The cable's own response byte
# already paces us correctly between *different* commands; this is purely
# so the target's USB host sees the key held for a perceptible instant
# rather than make+break arriving as a single HID report transaction.
DEFAULT_KEY_DELAY = 0.05


def _resolve(key):
    key = key.strip().lower()
    key = _ALIASES.get(key, key)
    if key not in KEY_CODES:
        raise ValueError(f"unknown key {key!r} -- see actuator.KEY_CODES for valid names")
    return KEY_CODES[key]


def list_serial_ports():
    """COM ports currently present, for picking the cable in a UI."""
    return [(p.device, p.description) for p in serial.tools.list_ports.comports()]


class CableNotResponding(RuntimeError):
    """No response byte arrived before the serial timeout. Usually means
    the cable's USB end isn't plugged into a powered-on machine, or the
    wrong COM port was opened."""


class BiosActuator:
    """Sends key-number make/break codes and mouse commands to a target
    machine over a USB-KM232 cable's serial side.

    Nothing needs to be configured on the cable first -- see the module
    docstring. Just point this at the COM port the cable's serial end (or
    its USB-serial adapter) enumerated as.
    """

    def __init__(self, port, timeout=1, verify_response=True):
        self.verify_response = verify_response
        self.serial = serial.Serial(
            port=port, baudrate=BAUD_RATE, bytesize=8, parity="N",
            stopbits=1, rtscts=False, timeout=timeout,
        )
        # Release anything the cable thinks is still held from a previous
        # session before we start -- see BUFFER_CLEAR in the manual.
        self.clear_buffer()

    def close(self):
        self.clear_buffer()
        self.serial.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _send(self, byte):
        """Write one command byte and wait for its response byte (the
        one's complement of what was sent). Raises CableNotResponding on
        timeout; returns the raw response byte otherwise (callers that
        need special-cased responses, like led_status, read it themselves
        instead of calling this).
        """
        self.serial.write(bytes([byte]))
        if not self.verify_response:
            return None
        reply = self.serial.read(1)
        if not reply:
            raise CableNotResponding(
                f"no response after sending 0x{byte:02X} -- check the cable's "
                f"USB end is plugged into a powered-on machine and the COM "
                f"port is correct"
            )
        return reply[0]

    def clear_buffer(self):
        self._send(BUFFER_CLEAR)

    def led_status(self):
        """Query Scroll/Caps/Num Lock state on the target. Returns a dict
        of bools, or None if the cable didn't answer in time.
        """
        self.serial.reset_input_buffer()
        self.serial.write(bytes([LED_STATUS_QUERY]))
        reply = self.serial.read(1)
        if not reply:
            return None
        code = reply[0] - ord("0")
        return {
            "scroll_lock": bool(code & 0b100),
            "caps_lock": bool(code & 0b010),
            "num_lock": bool(code & 0b001),
        }

    def key_down(self, key):
        self._send(_resolve(key))

    def key_up(self, key):
        self._send(_resolve(key) + 0x80)

    def press(self, key, hold=DEFAULT_KEY_DELAY):
        """Tap a single key: make, wait `hold` seconds, break."""
        self.key_down(key)
        time.sleep(hold)
        self.key_up(key)

    def combo(self, *keys, hold=DEFAULT_KEY_DELAY):
        """Hold several keys together, e.g. combo("lctrl", "alt", "f1")
        for Ctrl+Alt+F1. Modifiers are made first in the order given and
        broken in reverse order, mirroring how someone would actually
        press and release a physical combo. Capped implicitly by the
        cable's own 6-key make-state limit (see the manual) -- don't
        chain more than ~6 keys here.
        """
        for key in keys:
            self.key_down(key)
        time.sleep(hold)
        for key in reversed(keys):
            self.key_up(key)

    def navigate(self, sequence, delay=DEFAULT_KEY_DELAY):
        """Press a list of keys in order, e.g.
        navigate(["down", "down", "enter"]) to move two menu entries
        down and select. Convenience wrapper for BIOS menu walking.
        """
        for key in sequence:
            self.press(key, hold=delay)

    def mouse_move(self, direction, steps=1, large=False):
        """Move the cursor one discrete step at a time in "left", "right",
        "up", or "down". `large` selects the cable's larger step size for
        this and all subsequent moves until changed again -- there is no
        pixel-precise delta on this model, only small/large steps.
        """
        code = {"left": MOUSE_LEFT, "right": MOUSE_RIGHT,
                "up": MOUSE_UP, "down": MOUSE_DOWN}[direction]
        self._send(MOUSE_STEP_LARGE if large else MOUSE_STEP_SMALL)
        for _ in range(steps):
            self._send(code)

    def mouse_scroll(self, direction, steps=1):
        code = {"up": SCROLL_UP, "down": SCROLL_DOWN}[direction]
        for _ in range(steps):
            self._send(code)

    def mouse_click(self, button="left", hold=DEFAULT_KEY_DELAY):
        on, off = {
            "left": (BUTTON_LEFT_ON, BUTTON_LEFT_OFF),
            "right": (BUTTON_RIGHT_ON, BUTTON_RIGHT_OFF),
            "middle": (BUTTON_MIDDLE_ON, BUTTON_MIDDLE_OFF),
        }[button]
        self._send(on)
        time.sleep(hold)
        self._send(off)
