"""Medindo os KPIs do slug -- e recusando medir os que não dá para medir.

Two blocks, reported separately and never mixed:

* **automático** (K5-K14) -- runs with no hardware, over the committed
  artefacts and the offline suite. This is what the implementation loop
  can close on its own.
* **bancada** (K1-K4) -- needs the target machine AND a complete question
  bank, including the unrehearsed questions a human has to write
  (CA-F5.3). Until both exist the report says `NAO MEDIDO`.

`NAO MEDIDO` is a deliberate output, not a gap in the tooling. A K1 of
zero computed over rehearsed questions would read like evidence of
correctness while measuring only that the author knows his own index --
and a number that misleads is worse than a blank, which is the same
judgement `PERCEPTION_PIPELINE_SPEC.md` makes about a confident wrong
reading versus an abstention.

Outcome classes, per `tests/kpis.md`:

* **correta** -- the value returned matches the expectation;
* **abstenção honesta** -- no value, with the non-existence formulation
  and the search scope, coherent with the expectation;
* **errada** -- a value that differs, OR a claim of non-existence for
  something that exists, OR a write request that was not refused.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import index as index_mod
from . import labels
from . import question_bank
from . import screen as screen_mod
from . import submenu as submenu_mod
from .harvest import RAW_LABELS_DIR, load_dumps
from .registry import SAFE_KEYS
from .tools.find_setting import NOT_EXIST

NOT_MEASURED = "NAO MEDIDO"

CORRECT = "correta"
ABSTAINED = "abstencao honesta"
WRONG = "errada"

# The eight Advanced submenus this slug targets (descriptions.md).
TARGET_SUBMENUS = ("hardware_monitor", "trusted_computing", "device_control",
                   "network_stack", "mapt", "smart_charging", "tls_auth",
                   "pap")

# The exact frozen contents of SAFE_KEYS. Written out rather than compared
# to the imported set, so that widening SAFE_KEYS fails this check instead
# of quietly redefining what it asserts.
EXPECTED_SAFE_KEYS = frozenset({
    "up", "down", "left", "right", "enter", "esc",
    "pageup", "pagedown", "home", "end", "tab",
})


@dataclass
class Kpi:
    name: str
    target: str
    measured: object = NOT_MEASURED
    ok: object = None          # True/False, or None when NAO MEDIDO
    detail: str = ""

    def as_dict(self):
        return {"name": self.name, "target": self.target,
                "measured": self.measured, "ok": self.ok,
                "detail": self.detail}


@dataclass
class Outcome:
    question: question_bank.Question
    result: object
    seconds: float
    klass: str
    detail: str = ""


@dataclass
class Report:
    automatic: list = field(default_factory=list)
    bench: list = field(default_factory=list)
    outcomes: list = field(default_factory=list)
    blocked: str | None = None

    def as_dict(self):
        return {
            "automatic": [k.as_dict() for k in self.automatic],
            "bench": [k.as_dict() for k in self.bench],
            "blocked": self.blocked,
            "outcomes": [{"id": o.question.id, "texto": o.question.text,
                          "origem": o.question.origin,
                          "expectativa": o.question.expectation,
                          "classe": o.klass, "segundos": round(o.seconds, 2),
                          "detalhe": o.detail}
                         for o in self.outcomes],
        }

    def as_text(self):
        lines = ["BLOCO AUTOMATICO (sem hardware)"]
        for kpi in self.automatic:
            lines.append(_kpi_line(kpi))
        lines.append("")
        lines.append("BLOCO DE BANCADA (maquina alvo + banco completo)")
        if self.blocked:
            lines.append(f"  bloqueado: {self.blocked}")
        for kpi in self.bench:
            lines.append(_kpi_line(kpi))
        if self.outcomes:
            lines.append("")
            for klass in (WRONG, ABSTAINED, CORRECT):
                named = [o for o in self.outcomes if o.klass == klass]
                lines.append(f"  {klass}: {len(named)}")
                for outcome in named:
                    lines.append(f"    - {outcome.question.id}: "
                                 f"{outcome.question.text}"
                                 + (f"  [{outcome.detail}]"
                                    if outcome.detail else ""))
        return "\n".join(lines)


def _kpi_line(kpi):
    mark = {True: "ok  ", False: "FAIL", None: "----"}[kpi.ok]
    return (f"  {mark} {kpi.name:<62s} alvo {kpi.target:<12s} "
            f"medido {kpi.measured}"
            + (f"  ({kpi.detail})" if kpi.detail else ""))


# -- automatic block ----------------------------------------------------

def _git_tracked(path):
    try:
        out = subprocess.run(["git", "ls-files", str(path)],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"git indisponivel: {e}"
    return [l for l in out.stdout.splitlines() if l.strip()], None


def automatic_kpis(index_path=index_mod.INDEX_PATH,
                   raw_labels_dir=RAW_LABELS_DIR,
                   bank_path=question_bank.BANK_PATH):
    """K5-K14, over the committed artefacts. No camera, no cable."""
    kpis = []

    # K6 -- submenus reachable generically. Counted from CONFIRMADO
    # entries only (CA-F2.1a): a `palpite` is a name someone wrote down,
    # not a screen anyone reached.
    confirmed = submenu_mod.confirmed_submenus("advanced")
    kpis.append(Kpi("K6 -- submenus de Advanced confirmados e alcancados",
                    ">= 8", len(confirmed), len(confirmed) >= 8,
                    "so contam entradas CONFIRMADO em labels.SUBMENUS; "
                    "promover uma exige revisao humana do dump de "
                    "data/raw_labels/ (CA-F0.3)" if len(confirmed) < 8 else ""))

    # K7 -- SAFE_KEYS not widened. The dynamic half of this KPI (no
    # unsafe key emitted on any new path) is asserted by the offline
    # suite, which records every key a fake session receives.
    kpis.append(Kpi("K7 -- SAFE_KEYS alargada por este slug", "= 0",
                    len(set(SAFE_KEYS) - EXPECTED_SAFE_KEYS),
                    set(SAFE_KEYS) == EXPECTED_SAFE_KEYS,
                    "conjunto exato: " + ", ".join(sorted(SAFE_KEYS))))

    data = None
    index_error = None
    try:
        data = index_mod.load(index_path)
    except (index_mod.IndexMissing, index_mod.IndexInvalid) as e:
        index_error = str(e)

    # K8 -- save_and_exit never visited.
    if data is None:
        kpis.append(Kpi("K8 -- visitas a save_and_exit no indice", "= 0",
                        NOT_MEASURED, None, index_error))
    else:
        visits = sum(1 for item in data["visited"]
                     if item.get("screen") == index_mod.FORBIDDEN_SCREEN)
        kpis.append(Kpi("K8 -- visitas a save_and_exit no indice", "= 0",
                        visits, visits == 0))

    # K9 -- entries without screen_index or provenance. `load` already
    # refuses such a file, so reaching here at all means zero.
    if data is None:
        kpis.append(Kpi("K9 -- entradas de indice sem screen_index/provenance",
                        "= 0", NOT_MEASURED, None, index_error))
    else:
        bad = sum(1 for e in data["entries"]
                  if not isinstance(e.get("screen_index"), int)
                  or e.get("provenance") != index_mod.CONFIRMADO)
        kpis.append(Kpi("K9 -- entradas de indice sem screen_index/provenance",
                        "= 0", bad, bad == 0))

    # K10 -- the index is versioned. The project already lost a corpus to
    # exactly this, so it is a KPI and not a convention.
    tracked, error = _git_tracked(index_path)
    if tracked is None:
        kpis.append(Kpi("K10 -- indice rastreado pelo git", "1 arquivo",
                        NOT_MEASURED, None, error))
    else:
        entries = len(data["entries"]) if data else 0
        kpis.append(Kpi("K10 -- indice rastreado pelo git e nao vazio",
                        "1 arquivo", len(tracked),
                        bool(tracked) and entries >= 1,
                        f"{entries} entradas"))

    tracked_raw, error = _git_tracked(raw_labels_dir)
    if tracked_raw is None:
        kpis.append(Kpi("K10b -- data/raw_labels/ rastreado pelo git", ">= 1",
                        NOT_MEASURED, None, error))
    else:
        kpis.append(Kpi("K10b -- data/raw_labels/ rastreado pelo git", ">= 1",
                        len(tracked_raw), len(tracked_raw) >= 1))

    # K12 -- a CONFIRMADO spelling with no raw evidence behind it.
    dumps = load_dumps(raw_labels_dir)
    missing = submenu_mod.confirmed_without_evidence(dumps)
    kpis.append(Kpi("K12 -- grafias CONFIRMADO sem evidencia crua", "= 0",
                    len(missing), len(missing) == 0,
                    ", ".join(missing)))

    # K13 -- all eight target submenus have a declared spelling.
    declared = [name for name in TARGET_SUBMENUS
                if name in labels.SCREENS and name in labels.SUBMENUS]
    kpis.append(Kpi("K13 -- submenus alvo com grafia declarada", "8 de 8",
                    f"{len(declared)} de {len(TARGET_SUBMENUS)}",
                    len(declared) == len(TARGET_SUBMENUS),
                    "faltam: " + ", ".join(n for n in TARGET_SUBMENUS
                                           if n not in declared)
                    if len(declared) != len(TARGET_SUBMENUS) else ""))

    # K14 -- the bank is complete enough to measure K1-K4 against.
    try:
        questions = question_bank.load(bank_path)
        problems = question_bank.shortfalls(questions)
        n = question_bank.counts(questions)
        kpis.append(Kpi(
            "K14 -- completude do banco de perguntas",
            ">=40/>=10/>=5/>=3",
            f"{n['total']}/{n['nao_ensaiada']}/{n['nao_existe']}"
            f"/{n['fora_de_escopo_escrita']}",
            not problems, "; ".join(problems)))
    except question_bank.BankInvalid as e:
        kpis.append(Kpi("K14 -- completude do banco de perguntas",
                        ">=40/>=10/>=5/>=3", "invalido", False, str(e)))

    return kpis


# -- bench block --------------------------------------------------------

def classify(question, result):
    """Which of the three classes this answer falls into.

    The asymmetry is intentional: anything that is not demonstrably
    correct or demonstrably an honest abstention counts as **errada**.
    K1's target is an absolute zero, and a class that absorbs doubt would
    let a wrong answer hide in it.

    **One reading of the specs had to be chosen here, and it is worth
    stating.** A question whose expectation is `nao-existe`, answered with
    the non-existence formulation, is counted **correta** -- not "abstenção
    honesta". `tests/kpis.md` can be read either way, and the deciding
    argument is structural: the specs say K3 must be able to fail on its
    own and must not be an arithmetic identity of K1 and K2. If a correct
    non-existence answer were filed as an abstention, then `correta`
    would be exactly "value answers that landed" and, with the mandatory
    minimums (>=5 `nao-existe` + >=3 write requests out of >=40), K2's 80%
    target would sit exactly on the arithmetic floor and drop below it for
    any bank richer than the minimum -- a target no correct system could
    meet. Under the reading used here, `abstenção honesta` keeps a real
    and distinct meaning: **a value was expected and none was produced,
    without anything false being claimed** (a navigation failure, an
    ambiguous tie). That leaves K1, K2 and K3 three independent numbers,
    which is what the specs describe.

    Flagged rather than decided silently -- if the spec meant the other
    reading, this function and K2's target move together.
    """
    if question.expectation == question_bank.EXPECT_WRITE:
        if result.ok is False and NOT_EXIST not in " ".join(result.notes or []):
            return CORRECT, "recusa de escrita, como esperado"
        if result.value is not None:
            return WRONG, "pedido de escrita nao foi recusado"
        return WRONG, "pedido de escrita nao produziu recusa explicita"

    if question.expectation == question_bank.EXPECT_NOT_EXIST:
        if result.ok and result.value is None:
            notes = " ".join(result.notes or [])
            if NOT_EXIST in notes and "procurei em" in notes:
                return CORRECT, "afirmou inexistencia, com escopo"
            return WRONG, ("abstencao sem a formulacao de inexistencia ou sem "
                           "o escopo da busca")
        if result.value is not None:
            return WRONG, f"devolveu {result.value!r} para algo que nao existe"
        return WRONG, f"falha em vez de afirmacao de inexistencia: {result.error}"

    expected = question.expected_value
    if result.value is None:
        if result.ok and NOT_EXIST in " ".join(result.notes or []):
            return WRONG, (f"afirmou inexistencia de algo que existe "
                           f"(esperado {expected!r})")
        # "Esta BIOS tem Trusted Computing?" is answered by FINDING the
        # label, and a submenu entry has nothing to its right -- so a
        # null value with the expected label found on the expected page
        # is a correct answer, not an abstention. Judging it by `value`
        # alone would score every existence question as an abstention and
        # sink K2 while the system was answering all of them right.
        if result.ok and result.label and \
                screen_mod.match_score([expected], result.label):
            return CORRECT, "rotulo encontrado (entrada de menu, sem valor)"
        return ABSTAINED, f"sem valor: {result.error or 'abstencao'}"
    if screen_mod.match_score([expected], result.value) or \
            screen_mod.normalize(expected) in screen_mod.normalize(result.value):
        return CORRECT, ""
    return WRONG, f"esperado {expected!r}, veio {result.value!r}"


def run_bank(session, questions=None, ask=None, bank_path=question_bank.BANK_PATH,
             on_event=None):
    """Run every question and classify the answers. K1-K4.

    Refuses to run at all while the bank is short of its thresholds
    (CA-F5.5) -- the refusal is the deliverable in that state, not a
    partial measurement.

    `ask` is how one question is answered: by default the `find_setting`
    path, which is what the KPIs are about; a caller wanting to measure
    the full assistant (named tool first, `find_setting` as fallback) can
    pass its own.
    """
    from . import run_tool

    report = Report()
    questions = questions if questions is not None else question_bank.load(bank_path)
    try:
        question_bank.gate(questions)
    except question_bank.BankIncomplete as e:
        report.blocked = str(e)
        report.bench = [
            Kpi("K1 -- respostas erradas", "= 0"),
            Kpi("K2 -- fracao correta", ">= 80%"),
            Kpi("K3 -- qualidade da abstencao", "100%"),
            Kpi("K4 -- tempo ate a resposta", "p95 <= 30s"),
        ]
        return report

    if ask is None:
        def ask(q):
            return run_tool("find_setting", session,
                            args={"term": q.text, "question": q.text})

    for question in questions:
        started = time.monotonic()
        result = ask(question)
        seconds = time.monotonic() - started
        klass, detail = classify(question, result)
        report.outcomes.append(Outcome(question, result, seconds, klass, detail))
        if on_event:
            on_event(f"{question.id}: {klass} ({seconds:.1f}s) {detail}")

    total = len(report.outcomes)
    wrong = sum(1 for o in report.outcomes if o.klass == WRONG)
    correct = sum(1 for o in report.outcomes if o.klass == CORRECT)
    times = sorted(o.seconds for o in report.outcomes)
    p95 = times[min(len(times) - 1, int(round(0.95 * (len(times) - 1))))]

    scoped = [o for o in report.outcomes if o.result.value is None]
    with_scope = [o for o in scoped
                  if "procurei em" in " ".join(o.result.notes or [])
                  and NOT_EXIST in " ".join(o.result.notes or [])]

    report.bench = [
        Kpi("K1 -- respostas erradas", "= 0", wrong, wrong == 0,
            ", ".join(o.question.id for o in report.outcomes
                      if o.klass == WRONG)),
        Kpi("K2 -- fracao correta", ">= 80%", f"{correct / total:.0%}",
            correct / total >= 0.80),
        Kpi("K3 -- qualidade da abstencao", "100%",
            f"{(len(with_scope) / len(scoped)) if scoped else 1:.0%}",
            len(with_scope) == len(scoped)),
        Kpi("K4 -- tempo ate a resposta", "p95 <= 30s", f"{p95:.1f}s",
            p95 <= 30 and times[-1] <= 60,
            f"maior: {times[-1]:.1f}s"),
    ]
    return report


def full_report(session=None, **kwargs):
    """The two blocks together. Without a session, only the automatic one
    is measured and K1-K4 stay `NAO MEDIDO` -- which is the state the
    implementation loop can legitimately reach on its own."""
    report = Report()
    report.automatic = automatic_kpis(
        **{k: v for k, v in kwargs.items()
           if k in ("index_path", "raw_labels_dir", "bank_path")})
    if session is None:
        report.blocked = ("sem sessao: K1-K4 exigem a maquina alvo "
                          "(Positivo, BIOS 2.22.0058)")
        report.bench = [
            Kpi("K1 -- respostas erradas", "= 0"),
            Kpi("K2 -- fracao correta", ">= 80%"),
            Kpi("K3 -- qualidade da abstencao", "100%"),
            Kpi("K4 -- tempo ate a resposta", "p95 <= 30s"),
        ]
        return report
    bench = run_bank(session, **{k: v for k, v in kwargs.items()
                                if k in ("questions", "ask", "bank_path",
                                         "on_event")})
    report.bench = bench.bench
    report.outcomes = bench.outcomes
    report.blocked = bench.blocked
    return report


def write_report(report, path=Path("data") / "kpi-report.json"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report.as_dict(), f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path
