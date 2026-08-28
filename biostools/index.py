"""The machine's own label index: `rótulo -> onde ele está`.

What this buys. Without it, answering "qual o estado do Network Stack"
means guessing which screen to open, and the only guessing material
available was a hand-written list of hints per screen inside a tool's
description. That list is wrong the moment a BIOS model words something
differently, and it is silently wrong. With the index, the question is
answered from material **read off this machine**: the tour visits every
top-level screen except `save_and_exit`, descends into every CONFIRMADO
submenu, scrolls each page to the end (F1), and writes down every label,
the page it lives on, and the scroll position it is readable at.

**`data/label_index.json` is committed.** Not a cache, not a temp file --
a versioned artefact, same regime as `biostools/labels.py`. This project
already lost a test corpus by not committing it
(`docs/specs/p-specs/fixture-de-teste-nunca-versionada.md`) and the whole
generic answer path depends on this one.

**The `pages` section is what makes the index executable from disk.** An
entry says "screenful 2 of page p2"; scrolling back there needs to know
how tall p2 is (how many PgUps normalise it) and what p2's screenful 2
looked like when it was mapped (what proves arrival). Both live in the
`PageRecord`, so `page.reposition` works from a file rather than from a
scan still in memory. Without them the index would record positions no
one could return to.

**Every entry is CONFIRMADO.** The tour writes only what it read; there
is no prediction path here. The validator enforces that, so an index
edited by hand into carrying a guess fails loudly instead of feeding a
guess into an answer.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import labels
from . import submenu as submenu_mod
from .navigate import TOP_LEVEL_SCREENS, enter_main_menu_screen, looks_like_dialog
from .page import MAX_SCREENS, scan_page

# Fixed path inside the repository -- deliberately not configurable and
# deliberately not under a temp dir. See the module docstring.
INDEX_PATH = Path("data") / "label_index.json"

CONFIRMADO = "CONFIRMADO"
FORBIDDEN_SCREEN = "save_and_exit"
FORBIDDEN_REASON = ("nao visitada por decisao de projeto: todo controle "
                    "dessa tela confirma ou descarta configuracao (R6)")

TARGET_MODEL = "Positivo"
TARGET_BIOS_VERSION = "2.22.0058"


class IndexMissing(FileNotFoundError):
    """No index on disk. Distinct from a broken one: the fix is to run
    the tour, not to repair a file."""


class IndexInvalid(ValueError):
    """The index does not describe something answerable.

    Always names the offending entry or page. "invalid" on its own tells
    an operator nothing they can act on, and this file is meant to be
    repaired by re-running a tour against a specific screen.
    """


# -- validation ---------------------------------------------------------

def _require(condition, message):
    if not condition:
        raise IndexInvalid(message)


def validate(data):
    """Check the index describes positions something can actually return
    to. Raises `IndexInvalid` naming the offender; returns `data`.

    Pure: no camera, no cable, no imports beyond this package -- so it
    runs in the offline suite over the committed file and as
    `py -3.13 -m biostools validate-index` before a demo.
    """
    _require(isinstance(data, dict), "o indice nao e um objeto JSON")

    for key in ("bios_model", "bios_version", "captured_at"):
        _require(isinstance(data.get(key), str) and data[key].strip(),
                 f"cabecalho: campo {key!r} ausente ou vazio")
    _require(isinstance(data.get("visited"), list) and data["visited"],
             "cabecalho: 'visited' ausente ou vazio")
    _require(isinstance(data.get("skipped"), list),
             "cabecalho: 'skipped' ausente")
    _require(isinstance(data.get("pages"), list) and data["pages"],
             "'pages' ausente ou vazio -- sem PageRecord nenhuma entrada "
             "pode ser reposicionada")
    _require(isinstance(data.get("entries"), list) and data["entries"],
             "'entries' ausente ou vazio")

    _require(any(s.get("screen") == FORBIDDEN_SCREEN for s in data["skipped"]),
             f"{FORBIDDEN_SCREEN!r} tem de aparecer em 'skipped' com motivo "
             f"explicito -- a ausencia dela nao pode ser silenciosa (R6)")

    pages = {}
    for page in data["pages"]:
        page_id = page.get("page_id")
        _require(isinstance(page_id, str) and page_id.strip(),
                 f"pagina sem 'page_id': {page!r}")
        _require(page_id not in pages, f"page_id duplicado: {page_id!r}")

        screen = page.get("screen")
        _require(screen in TOP_LEVEL_SCREENS,
                 f"pagina {page_id!r}: 'screen' {screen!r} nao e uma tela de "
                 f"topo ({', '.join(sorted(TOP_LEVEL_SCREENS))})")
        _require(screen != FORBIDDEN_SCREEN,
                 f"pagina {page_id!r}: {FORBIDDEN_SCREEN!r} nao pode estar no "
                 f"indice (R6)")

        sub = page.get("submenu")
        if sub is not None:
            _require(sub in labels.SUBMENUS,
                     f"pagina {page_id!r}: submenu {sub!r} nao esta declarado "
                     f"em labels.SUBMENUS")
            _require(labels.SUBMENUS[sub]["parent"] == screen,
                     f"pagina {page_id!r}: submenu {sub!r} esta declarado sob "
                     f"{labels.SUBMENUS[sub]['parent']!r}, mas a pagina diz "
                     f"{screen!r}")

        total = page.get("total_screens")
        _require(isinstance(total, int) and not isinstance(total, bool)
                 and total >= 1,
                 f"pagina {page_id!r}: 'total_screens' deve ser inteiro >= 1, "
                 f"veio {total!r}")

        signatures = page.get("signatures")
        _require(isinstance(signatures, dict),
                 f"pagina {page_id!r}: 'signatures' ausente -- sem ela P2 nao "
                 f"tem contra o que verificar o reposicionamento")
        want = {str(i) for i in range(total)}
        got = {str(k) for k in signatures}
        _require(got == want,
                 f"pagina {page_id!r}: 'signatures' deveria ter exatamente as "
                 f"chaves {sorted(want, key=int)}, tem {sorted(got)}")
        for key, sig in signatures.items():
            _require(isinstance(sig, list),
                     f"pagina {page_id!r}: signatures[{key!r}] nao e uma lista")

        pages[page_id] = page

    for position, entry in enumerate(data["entries"]):
        where = f"entrada #{position} ({entry.get('label')!r})"
        _require(isinstance(entry.get("label"), str) and entry["label"].strip(),
                 f"{where}: 'label' ausente ou vazio")

        page_id = entry.get("page")
        _require(page_id in pages,
                 f"{where}: 'page' {page_id!r} nao existe em 'pages'")

        idx = entry.get("screen_index")
        _require(isinstance(idx, int) and not isinstance(idx, bool) and idx >= 0,
                 f"{where}: 'screen_index' ausente ou invalido ({idx!r}) -- "
                 f"posicao sem indice de tela nao e reposicionavel")
        _require(idx < pages[page_id]["total_screens"],
                 f"{where}: screen_index {idx} fora da pagina {page_id!r}, "
                 f"que tem total_screens={pages[page_id]['total_screens']}")

        value = entry.get("value", None)
        _require(value is None or isinstance(value, str),
                 f"{where}: 'value' deve ser string ou null, veio {value!r}")

        _require(entry.get("provenance") == CONFIRMADO,
                 f"{where}: provenance {entry.get('provenance')!r} -- o indice "
                 f"so aceita {CONFIRMADO!r}, o tour nunca grava material "
                 f"previsto ou adivinhado")

    return data


def load(path=INDEX_PATH):
    """Read and validate the committed index.

    Raises `IndexMissing` (run the tour) or `IndexInvalid` (naming what is
    wrong). Never returns a partially usable index: half an index would
    let an answer come from a position nobody can verify.
    """
    path = Path(path)
    if not path.exists():
        raise IndexMissing(
            f"indice de rotulos ausente em {path} -- rode o tour de F3 "
            f"(py -3.13 study_label_index.py --serial-port COM3) e comite o "
            f"arquivo gerado"
        )
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise IndexInvalid(f"{path} nao e JSON valido: {e}") from e
    return validate(data)


def coverage(data):
    """Human-readable scope of what the index actually covers.

    This is the sentence an abstention has to carry (K3): "não existe
    nesta máquina" is only honest when accompanied by where it was looked
    for and when. Without it the answer collapses back into the ambiguous
    "não achei" the whole slug exists to eliminate.
    """
    visited = []
    for item in data.get("visited", ()):
        sub = item.get("submenu")
        visited.append(f"{item.get('screen')}/{sub}" if sub else item.get("screen"))
    skipped = []
    for item in data.get("skipped", ()):
        sub = item.get("submenu")
        where = f"{item.get('screen')}/{sub}" if sub else item.get("screen")
        skipped.append(f"{where} ({item.get('reason')})")
    # Anything skipped that is not the deliberately-excluded
    # `save_and_exit` is a real hole in what "não existe" can mean, and
    # the answer has to say so. Without this, an index that skipped every
    # submenu (the honest state before F0's human review) would let
    # `find_setting` answer "esse ajuste não existe nesta máquina" about
    # a setting sitting one level down in Hardware Monitor -- a confident
    # false statement, which is precisely a K1 wrong answer.
    holes = [item for item in data.get("skipped", ())
             if item.get("screen") != FORBIDDEN_SCREEN]
    hole_text = ""
    if holes:
        named = []
        for item in holes:
            sub = item.get("submenu")
            named.append(f"{item.get('screen')}/{sub}" if sub
                         else str(item.get("screen")))
        hole_text = (
            f". ATENCAO -- cobertura incompleta: nao entrei em "
            f"{', '.join(named)}, entao 'nao existe' aqui significa 'nao "
            f"esta em nada que eu cobri', e nao uma varredura da BIOS "
            f"inteira")

    return {
        "visited": visited,
        "skipped": skipped,
        "holes": [h.get("submenu") or h.get("screen") for h in holes],
        "complete": not holes,
        "captured_at": data.get("captured_at"),
        "text": (f"procurei em: {', '.join(visited) or 'nada'}; "
                 f"nao coberto: {', '.join(skipped) or 'nada'}; "
                 f"indice capturado em {data.get('captured_at')}"
                 + hole_text),
    }


# -- building (the tour, P4) --------------------------------------------

def entries_from_scan(scan, page_id):
    """`LabelEntry` list for one mapped page.

    Every line of the page becomes an entry, paired line or not: a lone
    line ('Trusted Computing', a submenu entry) is exactly the kind of
    thing a question asks about, and dropping it because it has no value
    to its right would leave the index unable to say the setting exists.
    `value` is null for those -- null and "" are different answers.
    """
    pairs = scan.pairs()
    by_normalised = {}
    for label, item in pairs.items():
        by_normalised[label] = item["value"]

    entries = []
    for line in scan.unique_lines():
        text = line["text"].strip()
        entries.append({
            "label": text,
            "page": page_id,
            "screen_index": line["screen_index"],
            "value": by_normalised.get(text),
            "provenance": CONFIRMADO,
        })
    return entries


def _page_record(page_id, screen, submenu, scan):
    """One `PageRecord`.

    `screen_id` is recorded alongside the signatures because F4 verifies
    the page it landed on before reading anything off it (CA-F4.8), and
    "what this page's id was when it was mapped" is knowledge only the
    tour has. Optional on read: an index captured before this field
    existed still validates, and verification then falls back to the
    declared-spelling check.
    """
    from . import screen as screen_mod

    full = getattr(scan.last_reading, "full", None)
    return {
        "page_id": page_id,
        "screen": screen,
        "submenu": submenu,
        "total_screens": scan.total_screens,
        "screen_id": screen_mod.screen_id(full) if full else None,
        "signatures": {str(k): v for k, v in scan.signatures().items()},
    }


def tour(session, mode="keyboard", max_screens=MAX_SCREENS,
         bios_model=TARGET_MODEL, bios_version=TARGET_BIOS_VERSION,
         captured_at=None, on_event=None, source=None):
    """Visit every reachable page and write down what it says. P4.

    One session, handed in by the caller -- this never opens its own
    (R4/K11). One failure never aborts the run (CA-F3.8): a screen that
    could not be reached is recorded in `skipped` with its reason and the
    tour moves on, because a tour that dies on the third screen produces
    nothing at all, while one that skips it produces an index missing one
    page and saying so.
    """
    report = {
        "bios_model": bios_model,
        "bios_version": bios_version,
        "captured_at": captured_at or time.strftime("%Y-%m-%dT%H:%M:%S"),
        # Where the frames came from. An index built by replaying a saved
        # capture is just as real as one built live -- the material was
        # read off this machine either way -- but an operator debugging a
        # stale position needs to know which, because a replayed capture
        # cannot scroll and therefore covers only each page's first
        # screenful.
        "source": source or "tour ao vivo",
        "visited": [],
        "skipped": [{"screen": FORBIDDEN_SCREEN, "submenu": None,
                     "reason": FORBIDDEN_REASON}],
        "pages": [],
        "entries": [],
    }

    def emit(message):
        if on_event:
            on_event(message)

    for screen in TOP_LEVEL_SCREENS:
        if screen == FORBIDDEN_SCREEN:
            emit(f"{screen}: pulada -- {FORBIDDEN_REASON}")
            continue

        outcome, _ = enter_main_menu_screen(session, screen, mode=mode)
        if not outcome.ok:
            reason = (f"nao cheguei na tela: {outcome.reason}"
                      + (f" ({outcome.detail})" if outcome.detail else ""))
            report["skipped"].append({"screen": screen, "submenu": None,
                                      "reason": reason})
            emit(f"{screen}: pulada -- {reason}")
            continue

        scan = scan_page(session, max_screens=max_screens)
        if not scan.ok:
            report["skipped"].append({"screen": screen, "submenu": None,
                                      "reason": scan.error})
            emit(f"{screen}: pulada -- {scan.error}")
        else:
            page_id = screen
            report["pages"].append(_page_record(page_id, screen, None, scan))
            report["entries"] += entries_from_scan(scan, page_id)
            report["visited"].append({"screen": screen, "submenu": None})
            emit(f"{screen}: {scan.total_screens} screenful, "
                 f"{len(scan.unique_lines())} linhas")

        for sub in labels.submenus_of(screen):
            reason = submenu_mod.skip_reason(sub)
            if reason:
                report["skipped"].append({"screen": screen, "submenu": sub,
                                          "reason": reason})
                emit(f"{screen}/{sub}: pulado -- {reason}")
                continue

            arrival = submenu_mod.enter_submenu(session, sub, mode=mode,
                                                restore=False,
                                                max_screens=max_screens)
            if not arrival.ok:
                report["skipped"].append({
                    "screen": screen, "submenu": sub,
                    "reason": f"{arrival.reason}: {arrival.detail}"})
                emit(f"{screen}/{sub}: pulado -- {arrival.reason}")
                continue

            sub_scan = scan_page(session, max_screens=max_screens)
            if sub_scan.ok:
                page_id = f"{screen}/{sub}"
                report["pages"].append(
                    _page_record(page_id, screen, sub, sub_scan))
                report["entries"] += entries_from_scan(sub_scan, page_id)
                report["visited"].append({"screen": screen, "submenu": sub})
                emit(f"{screen}/{sub}: {sub_scan.total_screens} screenful, "
                     f"{len(sub_scan.unique_lines())} linhas")
            else:
                report["skipped"].append({"screen": screen, "submenu": sub,
                                          "reason": sub_scan.error})
                emit(f"{screen}/{sub}: pulado -- {sub_scan.error}")

            # Back up to the parent before the next submenu, looking
            # between presses -- ESC is not uniformly "up one level" here.
            session.press("esc")
            if looks_like_dialog(session.read_cursor()):
                session.press("esc")

    return report


def save(report, path=INDEX_PATH):
    """Validate, then write. In that order on purpose: an index that
    cannot be loaded back has no business being committed."""
    validate(report)
    path = Path(path)
    os.makedirs(path.parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path
