"""Scores the perception/ engine against the SAME ground truth as
test_selection.py -- same synthetic cases, same real AMI/Positivo photos,
same negative-capture sweep -- so the two are comparable on equal terms,
not on the strength of the claim in gui.py's --legacy help text ("better on
the vertical-sidebar BIOS and worse on AMI body items -- see the
measurements in ESTUDO_SELECAO.md"). Checked 2026-08-06: ESTUDO_SELECAO.md
has no mention of perception/E4-E9 at all. This script exists to produce
that missing measurement independently.

Unlike test_selection.py, this cannot replay cached OCR bboxes: E2
(Extraction) always runs its own OCR -- e2_extraction.py's
non-contamination rule treats a source's internal grouping as provenance,
never borrowed structure -- and E1 (Conditioning) may rectify/warp the
frame before anything downstream runs, so bboxes measured on the original
image are not guaranteed to land on the same pixels as the surface actually
used. Every case here therefore runs the real end-to-end pipeline against
the original image, exactly as gui.py's perception mode does live.

Stages are built once and reused across images -- only Acquisition is
rebuilt per frame -- for the same reason as gui.py's
_perception_worker_process: Extraction owns the loaded OCR model, and
rebuilding the whole pipeline per image would reload it every time and
dominate the runtime.

Run:
    py -3.13 test_perception.py            synthetic + real AMI + Positivo,
                                            plus a 60-image negative sample
                                            (a few minutes)
    py -3.13 test_perception.py --full      full negative sweep instead of
                                            the sample -- one real OCR pass
                                            per capture, no shortcut exists,
                                            budget 30-60+ minutes
"""
from ocr import DEFAULT_ENGINE
import argparse
import glob
import os
import sys
import time

import cv2

# OCR on a real photo can read CJK or other non-cp1252 glyphs out of noise
# (observed: a false positive whose "text" was a stray Chinese character) --
# a report script has no business crashing on the very output it exists to
# show. Windows' console/redirected-file default codec can't take that; UTF-8
# with substitution can.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from make_test_image import TEST_CASES
from perception.pipeline import run_pipeline
from perception.stages import (
    Acquisition, Characterisation, Conditioning, Equivalence, Extraction,
    Grouping, Identity, Regionalisation, Serialisation, StateInference, Typing,
)
from test_selection import POSITIVO_CASES, POSITIVO_KNOWN_WEAK_SIDEBAR, REAL_CASES, _image_path


def _warm_stages(engine=DEFAULT_ENGINE):
    return [
        Conditioning(),
        Extraction(engine=engine),
        Characterisation(),
        Regionalisation(),
        Grouping(),
        Equivalence(),
        StateInference(),
        Typing(),
        Identity(),
        Serialisation(view="full"),
    ]


def _run(warm, image):
    return run_pipeline([Acquisition(frames=[image])] + warm)


def _selected_texts(perception):
    """{content: State} for every primitive currently holding a 'selected'
    state -- the perception-side equivalent of selection.py's
    `highlighted` flag.
    """
    prims = perception.primitives_by_id()
    out = {}
    for state in perception.states:
        if state.name != "selected":
            continue
        prim = prims.get(state.element_id)
        if prim is not None and prim.content:
            out[prim.content] = state
    return out


def _match_prefix(text, expected_prefixes):
    return next((p for p in expected_prefixes if text.startswith(p)), None)


def score_synthetic(warm):
    all_ok = True
    for name, expected in TEST_CASES.items():
        if not os.path.exists(name):
            print(f"  {name}: MISSING -- run: py -3.13 make_test_image.py")
            all_ok = False
            continue

        image = cv2.imread(name)
        result = _run(warm, image)
        flagged = set(_selected_texts(result.perception))

        missed = expected - flagged
        extra = flagged - expected
        ok = not missed and not extra
        all_ok = all_ok and ok
        print(f"  {name}: {'OK' if ok else 'FAIL'} "
              f"flagged={sorted(flagged)} expected={sorted(expected)}"
              + (f" missed={sorted(missed)}" if missed else "")
              + (f" extra={sorted(extra)}" if extra else ""))
    return all_ok


def score_real(warm):
    all_ok = True
    for name, expected in REAL_CASES.items():
        image = cv2.imread(name + ".png")
        result = _run(warm, image)
        selected = _selected_texts(result.perception)

        matched_prefixes = set()
        wrong = []
        for text in selected:
            prefix = _match_prefix(text, expected)
            (matched_prefixes.add(prefix) if prefix else wrong.append(text))

        ok = matched_prefixes == set(expected) and not wrong
        all_ok = all_ok and ok
        print(f"  {os.path.basename(name)}: {'OK' if ok else 'FAIL'} "
              f"flagged={sorted(selected)} expected={sorted(expected)}"
              + (f" unexpected={wrong}" if wrong else ""))
    return all_ok


def score_positivo(warm):
    all_ok = True
    submenu_hits = submenu_total = 0
    for name, expected in POSITIVO_CASES.items():
        image = cv2.imread(_image_path(name))
        result = _run(warm, image)
        selected = _selected_texts(result.perception)

        sidebar_ok = expected["sidebar"] in selected
        sidebar_label = "OK" if sidebar_ok else "FAIL"
        if name in POSITIVO_KNOWN_WEAK_SIDEBAR:
            sidebar_label = "OK" if sidebar_ok else "known weak signal in selection.py -- not required here either"
        else:
            all_ok = all_ok and sidebar_ok

        submenu_expected = expected["submenu"]
        if submenu_expected is None:
            submenu_status = "n/a (negative case)"
        else:
            submenu_total += 1
            submenu_status = "OK" if submenu_expected in selected else "not caught"
            submenu_hits += submenu_expected in selected

        print(f"  {os.path.basename(name)}: sidebar={sidebar_label} submenu={submenu_status} "
              f"flagged={sorted(selected)}")

    print(f"  submenu selections also caught: {submenu_hits}/{submenu_total} "
          f"(selection.py currently gets 1/4 here -- tracked for comparison, not required to pass)")
    return all_ok


def score_captures(warm, limit=None):
    skip_bases = set(REAL_CASES) | set(POSITIVO_CASES)
    paths = sorted(glob.glob("captures/*.png")) + sorted(glob.glob("captures/*.jpg"))
    candidates = [p for p in paths if p.rsplit(".", 1)[0] not in skip_bases]
    total_available = len(candidates)
    if limit:
        candidates = candidates[:limit]

    total_primitives = total_flagged = total_abstentions = errors = 0
    offenders = []
    t0 = time.time()
    for i, path in enumerate(candidates):
        image = cv2.imread(path)
        if image is None:
            continue
        try:
            result = _run(warm, image)
        except Exception as exc:                              # noqa: BLE001
            errors += 1
            print(f"    {os.path.basename(path)}: ERROR {exc}")
            continue

        perception = result.perception
        selected = _selected_texts(perception)
        total_primitives += sum(1 for p in perception.primitives if p.is_symbolic and p.content)
        total_flagged += len(selected)
        total_abstentions += len(perception.abstentions)
        if selected:
            offenders.append((os.path.basename(path), sorted(selected)))
        if (i + 1) % 25 == 0:
            print(f"  ... {i + 1}/{len(candidates)} done ({time.time() - t0:.0f}s elapsed)")

    rate = 100 * total_flagged / max(1, total_primitives)
    scope = f"{len(candidates)}/{total_available} captures" if limit else f"all {total_available} captures"
    print(f"  {total_flagged}/{total_primitives} symbolic primitives flagged 'selected' "
          f"({rate:.1f}%) across {scope}"
          + (" -- pass --full for the complete sweep" if limit else ""))
    print(f"  {total_abstentions} abstentions total across the sweep "
          f"(state-level uncertainty declared instead of guessed -- not itself a false positive)")
    if errors:
        print(f"  {errors} image(s) raised an exception instead of scoring -- see ERROR lines above")
    for name, texts in offenders[:10]:
        print(f"    {name}: {texts}")
    if len(offenders) > 10:
        print(f"    ... and {len(offenders) - 10} more images with flags")
    return rate


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                         help="Run the complete negative sweep instead of a 60-image sample. "
                              "Slow: one real OCR pass per capture, no cached-JSON shortcut "
                              "is possible for this pipeline (see module docstring).")
    parser.add_argument("--engine", default=DEFAULT_ENGINE)
    args = parser.parse_args()

    warm = _warm_stages(engine=args.engine)

    print("Synthetic cases -- inverted background bar (exact match required):")
    synthetic_ok = score_synthetic(warm)

    print("\nReal AMI BIOS photos -- selection by text colour (exact match required):")
    real_ok = score_real(warm)

    print("\nReal Positivo BIOS photos -- vertical sidebar/submenu (sidebar required, submenu tracked):")
    positivo_ok = score_positivo(warm)

    print(f"\nOther captures -- no genuine selection, any 'selected' state is a false positive "
          f"({'full sweep' if args.full else 'sample of 60 -- pass --full for the complete sweep'}):")
    false_positive_rate = score_captures(warm, limit=None if args.full else 60)

    print(f"\nperception/: synthetic_ok={synthetic_ok} real_ok={real_ok} positivo_ok={positivo_ok} "
          f"false_positive_rate={false_positive_rate:.1f}%")
    print("selection.py (test_selection.py), for comparison: 3/3 synthetic, 3/3 real AMI, "
          "Positivo sidebar 4/5 + submenu 1/4, false positives 2.0% over 364 captures.")
    print("\nNo pass/fail gate is enforced here on purpose -- there is no threshold for this "
          "engine yet to gate against, and inventing one now would be guessing, not measuring. "
          "That's a decision to make from this output, not something this script should decide.")
