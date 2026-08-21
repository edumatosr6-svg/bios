"""First read-act-verify demo: navigate down through the BIOS menu,
confirming via camera+OCR which entry is actually selected at each step
(not just assuming the keypress landed), until "Hardware Monitor" is
reached -- then open it and answer "what is the CPU temperature?" by
reading the resulting screen.

Ties together pieces that, until now, had only been exercised separately:
selection detection (ocr.py + selection.py) for the "verify" half, and
actuator.py's USB-KM232 control for the "act" half. Deliberately uses the
legacy selection.py path (not perception/), since that is what already
scored well on real AMI/Positivo photos -- see the project notes on the
perception/selection.py tradeoff if that ever needs revisiting.

Kept as a standalone script, not merged into watcher.py/gui.py, because
this is a one-shot navigate-to-target loop (drives the target machine),
not a passive continuous capture loop -- the two behaviours don't belong
behind the same flags.
"""
import argparse
import re
import time

import cv2

from actuator import BiosActuator, CableNotResponding
from capture import resolve_camera_source
from ocr import DEFAULT_ENGINE, ENGINE_CHOICES, create_ocr_engine


def _settle_frame(cap, discard=2):
    """Discard a couple of frames so the BIOS's own highlight-bar redraw
    has settled before we trust what we read. Kept small on purpose -- an
    HDMI capture card is a direct digital feed, not a photographed
    screen, so it has no auto-exposure/auto-focus settle time the way a
    webcam pointed at a monitor does.
    """
    frame = None
    for _ in range(discard):
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError("failed to read frame from camera")
    return frame


def _highlighted_lines(ocr_result):
    """(text, region) for every OCR line selection.py flagged as the
    current selection -- there can be more than one at once (e.g. an
    active tab plus a focused item within it).
    """
    out = []
    for block in ocr_result["blocks"]:
        for line in block["lines"]:
            if line.get("highlighted"):
                out.append((line["text"], line.get("region")))
    return out


def _normalize(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _is_hardware_monitor(text):
    """Tolerant of the real-world spelling variants BIOSes use for this
    entry (Hardware Monitor / H/W Monitor / HW Monitor) and of OCR noise,
    without being so loose it fires on an unrelated line.
    """
    norm = _normalize(text)
    return "monitor" in norm and ("hardware" in norm or norm.startswith("hw") or "hwmonitor" in norm)


def navigate_to_hardware_monitor(cap, engine, bios, max_steps, settle_delay):
    """Presses "down" and re-reads the selection after each press, only
    ever trusting what the camera actually shows -- never assuming a
    keypress landed just because it was sent successfully.
    """
    import selection as selection_mod

    for step in range(1, max_steps + 1):
        frame = _settle_frame(cap)
        ocr_start = time.monotonic()
        result = engine.read(frame)
        ocr_elapsed = time.monotonic() - ocr_start
        selection_mod.annotate_selection(frame, result["blocks"])
        highlighted = _highlighted_lines(result)
        print(f"[passo {step}] OCR levou {ocr_elapsed:.1f}s")

        if not highlighted:
            print(f"[passo {step}] nenhuma selecao visivel ainda -- tentando de novo")
        else:
            for text, region in highlighted:
                print(f"[passo {step}] selecionado: {text!r} (regiao={region})")
            if any(_is_hardware_monitor(text) for text, _ in highlighted):
                print(f"Cheguei em 'Hardware Monitor' apos {step} passo(s).")
                return True

        bios.press("down")
        time.sleep(settle_delay)

    return False


def _flatten_lines(ocr_result):
    return [line for block in ocr_result["blocks"] for line in block["lines"]]


def _row_text(lines, target, y_tolerance_ratio=0.6):
    """BIOS field tables are usually two columns (label, value) far apart
    in x -- OCR frequently splits them into separate "lines" even though
    they sit on the same visual row. Groups everything whose vertical
    centre is close to the target's and reads them left-to-right, so a
    value sitting in a different OCR line/block from its label is still
    found.
    """
    tb = target.get("bbox")
    if not tb:
        return target["text"]
    theight = tb["height"] or 1
    tcenter = tb["top"] + theight / 2

    row = [target]
    for line in lines:
        if line is target:
            continue
        lb = line.get("bbox")
        if not lb:
            continue
        lcenter = lb["top"] + (lb["height"] or 1) / 2
        if abs(lcenter - tcenter) <= theight * y_tolerance_ratio:
            row.append(line)

    row.sort(key=lambda l: (l.get("bbox") or {}).get("left", 0))
    return " ".join(l["text"] for l in row)


def find_cpu_temperature(ocr_result):
    """Scans OCR lines for one mentioning both "cpu" and "temp", joins it
    with whatever else sits on the same visual row (see _row_text), and
    tries to pull a numeric value with a unit out of that combined text.
    Returns (matching_line_text, extracted_value) -- either may be None.
    """
    lines = _flatten_lines(ocr_result)
    for line in lines:
        low = line["text"].lower()
        if "cpu" in low and "temp" in low:
            row_text = _row_text(lines, line)
            match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:°|deg)?\s*[cf]\b", row_text.lower())
            if not match:
                # Unit letter/degree sign sometimes gets dropped by OCR --
                # fall back to the first plain number on the row.
                match = re.search(r"-?\d+(?:\.\d+)?", row_text)
            return line["text"], (match.group(0) if match else None), row_text
    return None, None, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-source", default="0",
                         help="Numeric webcam index or a stream URL (see capture.py)")
    parser.add_argument("--serial-port", required=True,
                         help="COM port the USB-KM232's serial end (or its USB-serial "
                              "adapter) enumerated as, e.g. COM3")
    parser.add_argument("--engine", choices=ENGINE_CHOICES, default=DEFAULT_ENGINE)
    parser.add_argument("--lang", default=None)
    parser.add_argument("--max-steps", type=int, default=20,
                         help="Safety cap on how many 'down' presses to try before giving up")
    parser.add_argument("--settle-delay", type=float, default=0.3,
                         help="Seconds to wait after each keypress before trusting the camera")
    args = parser.parse_args()

    resolved = resolve_camera_source(args.camera_source)
    cap = cv2.VideoCapture(resolved)
    if not cap.isOpened():
        raise SystemExit(f"could not open camera source {resolved!r}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    print(f"Carregando OCR engine ({args.engine})...")
    engine = create_ocr_engine(args.engine, lang=args.lang)

    try:
        with BiosActuator(args.serial_port) as bios:
            reached = navigate_to_hardware_monitor(
                cap, engine, bios,
                max_steps=args.max_steps, settle_delay=args.settle_delay,
            )
            if not reached:
                print(f"\nNao cheguei em 'Hardware Monitor' depois de {args.max_steps} passos -- parando.")
                return

            print("Abrindo 'Hardware Monitor' (Enter)...")
            bios.press("enter")
            time.sleep(args.settle_delay)

            frame = _settle_frame(cap)
            result = engine.read(frame)
            line_text, value, row_text = find_cpu_temperature(result)

            print()
            if value:
                print(f"Resposta: a temperatura da CPU e {value}")
                print(f"(linha OCR de origem: {line_text!r}, linha combinada: {row_text!r})")
            elif line_text:
                print(f"Achei uma linha sobre temperatura da CPU mas nao consegui extrair o numero.")
                print(f"Linha do rotulo: {line_text!r}")
                print(f"Linha combinada (mesma altura): {row_text!r}")
            else:
                print("Nao encontrei nenhuma linha mencionando temperatura da CPU nessa tela.")
                print("Texto completo lido, para conferencia manual:")
                print(result["full_text"])
    except CableNotResponding as e:
        raise SystemExit(f"cabo nao respondeu: {e}")
    finally:
        cap.release()


if __name__ == "__main__":
    main()
