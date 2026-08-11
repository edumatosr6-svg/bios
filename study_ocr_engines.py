"""Comparative study: which OCR engine should feed the perception engine?

    py -3.13 study_ocr_engines.py                 # both halves
    py -3.13 study_ocr_engines.py --speed         # how fast
    py -3.13 study_ocr_engines.py --accuracy      # how correct
    py -3.13 study_ocr_engines.py --engines rapidocr-openvino paddleocr

Two halves, in one file because they are one decision and answering only
half of it picks the wrong engine: the fastest engine measured here
(winocr, ~0.3s) is also the least accurate by a wide margin, and the most
accurate is unusably slow. Neither number decides alone.

**Speed** runs each engine in its own subprocess, sequentially, never
concurrently: CPU-bound engines competing for the same cores would make
each other look slower than they are. The isolation also means a crash in
one engine cannot take the comparison down, and an engine that is not
installed shows as UNAVAILABLE in the table instead of breaking the run.

**Accuracy** scores through the *full perception engine* rather than
against OCR output alone, because the pipeline is what consumes the OCR.
Two numbers, because they diverge: TEXT asks whether the OCR read the
string the ground truth names (an engine that cannot read "Save & Exit"
can never report it, however good the later stages are), STATE asks
whether the engine then concluded the right selection.

Ground truth is imported from test_selection.py and make_test_image.py
rather than restated here, so it cannot drift from the suite that owns
it. Measurements and conclusions live in docs/studies/estudo-motores-ocr.md.

**Scoring caveat, learned the expensive way.** POSITIVO_CASES declares
both a `sidebar` and a `submenu` per fixture. An earlier version scored
only `sidebar` and counted correct `submenu` detections as false
positives -- which inverted the ranking, punishing the engines that found
*more* of the ground truth. Both are scored.
"""
import argparse
import json
import os
import subprocess
import sys
import time

os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

import cv2

cv2.setLogLevel(0)

from ocr import ENGINE_CHOICES

DEFAULT_IMAGE = "captures/20260806-144020_auto.png"


# --------------------------------------------------------------- speed

def _speed_of(engine: str, image_path: str) -> dict:
    """One engine, in its own interpreter. See the module docstring."""
    proc = subprocess.run(
        [sys.executable, __file__, "--_worker", engine, "--input", image_path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        error = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "unknown error"
        return {"engine": engine, "ok": False, "error": error}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"engine": engine, "ok": False,
                "error": f"could not parse worker output: {proc.stdout[-300:]!r}"}


def _worker(engine: str, image_path: str) -> None:
    """Inside the subprocess: one JSON line on stdout, success or failure,
    so the parent never has to guess what happened.
    """
    from ocr import create_ocr_engine

    result: dict = {"engine": engine, "ok": False}
    t0 = time.perf_counter()
    try:
        engine_obj = create_ocr_engine(engine)
    except Exception as e:                                    # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
        print(json.dumps(result))
        return
    result["construct_s"] = round(time.perf_counter() - t0, 2)

    image = cv2.imread(image_path)
    t0 = time.perf_counter()
    try:
        data = engine_obj.read(image)
    except Exception as e:                                    # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
        print(json.dumps(result))
        return
    result["read_s"] = round(time.perf_counter() - t0, 2)

    lines = [line["text"] for block in data.get("blocks", []) for line in block["lines"]]
    result.update(ok=True, n_lines=len(lines), sample=lines[:5])
    print(json.dumps(result))


def run_speed(engines, image_path):
    print(f"\nSPEED -- {image_path}")
    width = max(len(e) for e in engines) + 1
    header = (f"{'engine':<{width}} {'construct':>10} {'read':>8} "
              f"{'total':>8} {'lines':>6}  sample")
    print(header)
    print("-" * len(header))
    for engine in engines:
        result = _speed_of(engine, image_path)
        if not result.get("ok"):
            print(f"{engine:<{width}} {'--':>10} {'--':>8} {'--':>8} {'--':>6}  "
                  f"UNAVAILABLE: {result.get('error', 'unknown error')}")
            continue
        total = result["construct_s"] + result["read_s"]
        print(f"{engine:<{width}} {result['construct_s']:>9.2f}s {result['read_s']:>7.2f}s "
              f"{total:>7.2f}s {result['n_lines']:>6}  "
              f"{', '.join(result['sample'][:3])}")
    print("\n'read' is the per-frame cost in warm use, which is what the GUI pays; "
          "'construct' happens once per session.")


# ------------------------------------------------------------ accuracy

def _cases():
    """Every fixture with declared ground truth, as (path, expected).

    Missing files are reported rather than skipped silently: the suite
    already references one fixture that was never committed, and a
    validation that quietly scores fewer cases than it claims is worse
    than one that fails loudly.
    """
    from make_test_image import TEST_CASES
    from test_selection import POSITIVO_CASES, REAL_CASES

    cases = [(name, set(expected)) for name, expected in TEST_CASES.items()]
    for base, truth in POSITIVO_CASES.items():
        expected = {truth["sidebar"]}
        if truth.get("submenu"):
            expected.add(truth["submenu"])
        cases.append((base + ".jpg", expected))
    cases += [(base + ".png", set(truth)) for base, truth in REAL_CASES.items()]
    return cases


def _norm(text):
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _reads(expected, texts):
    """Prefix match on alphanumerics only -- OCR spelling varies between
    shots, which is why test_selection.py matches its ground truth the
    same way.
    """
    want = _norm(expected)
    return bool(want) and any(want in _norm(t) or _norm(t).startswith(want) for t in texts)


def _score(engine, path, expected):
    from perception import perceive

    image = cv2.imread(path)
    if image is None:
        return None
    perception = perceive(frames=[image], engine=engine).perception
    by_id = perception.primitives_by_id()

    read = [p.content for p in perception.primitives if p.is_symbolic and p.content]
    selected = [by_id[s.element_id].content for s in perception.states
                if by_id.get(s.element_id) and by_id[s.element_id].content]
    return {
        "read_ok": sum(1 for e in expected if _reads(e, read)),
        "hits": sum(1 for e in expected if _reads(e, selected)),
        "total": len(expected),
        "extra": [t for t in selected if not any(_reads(e, [t]) for e in expected)],
        "n_read": len(read),
    }


def run_accuracy(engines):
    cases = _cases()
    summary = {}
    for engine in engines:
        print(f"\nACCURACY -- {engine}")
        rows = []
        for path, expected in cases:
            try:
                result = _score(engine, path, expected)
            except Exception as exc:                          # noqa: BLE001
                print(f"  {os.path.basename(path):44} ERROR {type(exc).__name__}: {exc}")
                continue
            if result is None:
                print(f"  {os.path.basename(path):44} MISSING FILE -- not scored")
                continue
            rows.append(result)
            print(f"  {os.path.basename(path):44} text={result['read_ok']}/{result['total']} "
                  f"state={result['hits']}/{result['total']} lines={result['n_read']:3}"
                  + (f" extra={result['extra']}" if result["extra"] else ""), flush=True)
        summary[engine] = rows

    print(f"\n{'engine':24} {'text read':>12} {'selection':>12} {'unexpected':>12}")
    print("-" * 64)
    for engine, rows in summary.items():
        if not rows:
            print(f"{engine:24} {'(no cases scored)':>38}")
            continue
        total = sum(r["total"] for r in rows)
        print(f"{engine:24} {sum(r['read_ok'] for r in rows):>5}/{total:<6} "
              f"{sum(r['hits'] for r in rows):>5}/{total:<6} "
              f"{sum(len(r['extra']) for r in rows):>12}")

    print("\n'unexpected' counts anything flagged that the ground truth does not "
          "name -- not automatically a false positive. On the Positivo save-exit "
          "fixture it catches 'Save Options', a section header that genuinely "
          "differs in colour from the list below it: an E6 role-separation gap, "
          "not an OCR error. Read the per-case lines before judging.")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--speed", action="store_true", help="time each engine")
    parser.add_argument("--accuracy", action="store_true",
                        help="score each engine against the ground truth")
    parser.add_argument("--engines", nargs="+", default=ENGINE_CHOICES)
    parser.add_argument("--input", default=DEFAULT_IMAGE,
                        help="image to time (--speed only)")
    parser.add_argument("--_worker", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args._worker:
        _worker(args._worker, args.input)
        return

    both = not (args.speed or args.accuracy)
    if args.speed or both:
        run_speed(args.engines, args.input)
    if args.accuracy or both:
        run_accuracy(args.engines)


if __name__ == "__main__":
    main()
