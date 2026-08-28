"""Tool 6: o caminho universal de resposta -- qualquer ajuste, sem tool nomeada.

Every tool before this one answers a question fixed when it was written.
`goto_screen` widened that to "any of the six sidebar screens", but still
had to guess WHICH screen a subject lives on, and the guessing material
was a hand-written list of hints inside its own description ("Fast Boot
fica em boot, senhas em security"). That list is a maintenance trap and,
worse, a silent one: it is wrong the moment a BIOS words something
differently, and nothing notices.

`find_setting` replaces the guess with material read off this machine.
`data/label_index.json` (F3) already says which page every label lives on
and at which scroll position; this tool looks the term up there, walks to
that page (F2 when it is a submenu), scrolls exactly to that position
(P2), verifies it landed where the index said, and reads the value.

**Three outcomes, and keeping them apart is the whole design:**

* found and read -- `ok=True`, `value` set;
* **not in this BIOS** -- `ok=True`, `value=None`, and a positive
  statement of knowledge ("não existe na BIOS desta máquina") together
  with where it looked and when the index was captured. This is an
  ANSWER, not a failure, and it is the one an operator most needs to be
  able to trust;
* failure -- `ok=False`, with what broke.

Collapsing the last two into one ambiguous "não achei" is exactly what
`descriptions.md` set out to eliminate, so their messages never overlap.

**The read-only guard lives here as well as in the assistant, on
purpose.** `assistant.py` decides which tool answers a question and pulls
`term` out of it; that is a model's judgment. The boundary that says this
system never writes to a BIOS must not depend on a model's judgment, so
the same check runs again here, over `term` and `question` both.
Redundancy in a safety barrier is not duplication to be refactored away.
"""
from __future__ import annotations

import re

from .. import index as index_mod
from .. import labels
from .. import screen as screen_mod
from .. import submenu as submenu_mod
from ..navigate import enter_main_menu_screen
from ..page import lines_of, reposition
from ..registry import Tool, ToolResult, register

# The exact wording of the "this machine does not have it" answer. A
# constant because K3 asserts on it and because every abstention has to
# use the SAME formulation -- an operator learns one sentence, not five
# variations of "não achei".
NOT_EXIST = "esse ajuste não existe na BIOS desta máquina"

# Verbs that mean the operator is asking for a CHANGE. A declared list,
# matched on word boundaries -- not a cleverness that infers intent, for
# the same reason labels.py declares spellings: an inferred refusal is a
# wrong answer with a confident face.
#
# Deliberately conservative. CA-F4.9: when in doubt this must NOT refuse,
# because reading is harmless and refusing a legitimate question in front
# of a customer is the expensive mistake. So it lists imperative and
# infinitive forms ("desliga", "ativar") and leaves participles and nouns
# alone -- "está ligado", "a configuração do Network Stack" and "qual o
# valor definido" all read as questions, which is what they are.
WRITE_VERBS = (
    # PT-BR -- imperativo e infinitivo
    "liga", "ligue", "ligar",
    "desliga", "desligue", "desligar",
    "ativa", "ative", "ativar",
    "desativa", "desative", "desativar",
    "habilita", "habilite", "habilitar",
    "desabilita", "desabilite", "desabilitar",
    "muda", "mude", "mudar",
    "altera", "altere", "alterar",
    "troca", "troque", "trocar",
    "configura", "configure", "configurar",
    "ajusta", "ajuste", "ajustar",
    "grava", "grave", "gravar",
    "salva", "salve", "salvar",
    "aplica", "aplique", "aplicar",
    "reseta", "resete", "resetar",
    "restaura", "restaure", "restaurar",
    "apaga", "apague", "apagar",
    "remove", "remova", "remover",
    "desmarca", "desmarque", "desmarcar",
    # EN
    "set", "change", "enable", "disable", "turn", "toggle", "modify",
    "write", "save", "apply", "reset", "configure", "update", "switch",
)

_WRITE_RE = re.compile(r"\b(?:%s)\b" % "|".join(map(re.escape, WRITE_VERBS)),
                       re.IGNORECASE)

# Words after which the next word is an adjective describing a state, not
# an order to change one. Portuguese collapses the two: 'ativa o TPM' is
# an imperative, 'está ativa' is 'is active'. Measured on this project's
# own question bank -- "A proteção de escrita da flash está ativa?" is a
# plain read question and was being refused. Declared, like everything
# else here, rather than inferred.
_COPULAS = ("esta", "está", "estao", "estão", "e", "é", "sao", "são",
            "seja", "fica", "ficam", "foi", "for", "estiver")

_COPULA_RE = re.compile(
    r"\b(?:%s)\s+$" % "|".join(map(re.escape, _COPULAS)), re.IGNORECASE)

READ_ONLY_REFUSAL = (
    "pedido de ALTERACAO recusado: este sistema é somente leitura e não "
    "envia nenhuma tecla capaz de mudar a BIOS (registry.SAFE_KEYS não "
    "inclui '+', '-', F10 ou 'y'). É uma fronteira deliberada, não uma "
    "limitação temporária -- posso LER qualquer ajuste e dizer como ele "
    "está, mas quem muda a configuração é uma pessoa."
)


def _is_declared_name(text):
    """True when `text` IS a declared label, rather than a sentence.

    'Save & Exit' and 'Salvar e Sair' are spellings of a screen, not
    requests to save anything, and refusing to look one up because the
    word 'save' is in it would be a false refusal of a perfectly
    read-only question. The exemption is exact-match-only (`match_score`
    == 2, whole term against a whole declared spelling), so it cannot
    swallow a sentence that merely CONTAINS a declared name: 'salva o
    Fast Boot' is not a declared spelling of anything and stays refused.
    """
    for table in (labels.FIELDS, labels.SCREENS):
        for spellings in table.values():
            if screen_mod.match_score(spellings, text) == 2:
                return True
    return False


def _change_verb(text, command_only):
    """The change verb in `text`, or None.

    `command_only` is the difference between the two inputs this guard
    sees, and it matters:

    * `question` is a SENTENCE, so a change verb anywhere in it is a
      change request -- "por favor desliga o Fast Boot".
    * `term` is a NAME. BIOS setting names legitimately contain these
      words: 'Flash Write Protection', 'Save & Exit', 'Removable Storage
      Devices Policy'. Refusing to look up 'Flash Write Protection'
      because it contains 'Write' would be a false refusal of exactly the
      kind CA-F4.9 says to avoid -- so in a term the verb only counts
      when it OPENS the string, which is what makes 'ativar TPM' a
      command and 'Flash Write Protection' a name.
    """
    for found in _WRITE_RE.finditer(text):
        if command_only and found.start() != 0:
            continue
        if _COPULA_RE.search(text[:found.start()]):
            continue
        return found.group(0)
    return None


def write_request(term=None, question=None):
    """The change verb behind this request, or None if it only reads."""
    for text, command_only in ((term, True), (question, False)):
        if not text or _is_declared_name(text):
            continue
        verb = _change_verb(text, command_only)
        if verb:
            return verb
    return None


def concept_spellings(term):
    """Declared spellings of every concept `term` plausibly names.

    This is how "temperatura da CPU" reaches an index entry spelled 'CPU
    Temperature': the term is matched against `labels.FIELDS` /
    `labels.SCREENS` -- declared wordings, reviewed by a person -- and the
    search then runs over that concept's whole spelling list. It is not a
    translation step and not a synonym engine; a term matching nothing
    declared is searched literally and, failing that, honestly reported as
    absent.

    **Expansion requires an EXACT normalised match, never containment.**
    Containment was tried and is actively harmful here: `SCREENS["boot"]`
    contains the spelling 'Boot', 'boot' is a substring of
    'securebootcustommode', so a search for the (non-existent) 'Secure
    Boot Custom Mode' expanded to 'Boot' and then tied against every line
    on the Boot page -- turning a clean "não existe nesta máquina" into a
    ten-way abstention. Exact-only keeps expansion to the case it was
    written for: an operator naming the same concept in other words.

    Two tables are consulted, and only one of them is screen text.
    `labels.FIELDS`/`labels.SCREENS` are how the BIOS spells things;
    `labels.TERMS` is how a person asks for them. They are kept apart on
    purpose (see `labels.TERMS`), so this is the one place the two sides
    meet -- a hit in either resolves to the concept, and the search then
    runs over that concept's SCREEN spellings, which is what the index
    actually contains.
    """
    targets = [term]

    def add(canonical):
        for spelling in labels.FIELDS.get(canonical, ()) or labels.SCREENS.get(canonical, ()):
            if spelling not in targets:
                targets.append(spelling)

    for table in (labels.FIELDS, labels.SCREENS):
        for spellings in table.values():
            if screen_mod.match_score(spellings, term) == 2:
                targets += [s for s in spellings if s not in targets]
    for canonical, wordings in labels.TERMS.items():
        if screen_mod.match_score(wordings, term) == 2:
            add(canonical)
    return targets


def search(data, term):
    """`(best_score, [entries])` for `term` against the index.

    Returns every entry tied at the best score, so the caller can abstain
    on a tie instead of taking whichever came first. Preferring exact over
    containment is `match_score`'s own ranking -- 'Main' is contained in
    'Domain Name', and an index spanning several pages offers plenty of
    chances for a loose match to outrank the right one.
    """
    targets = concept_spellings(term)
    best_score, best = 0, []
    for entry in data.get("entries", ()):
        score = screen_mod.match_score(targets, entry.get("label", ""))
        if not score:
            continue
        if score > best_score:
            best_score, best = score, [entry]
        elif score == best_score:
            best.append(entry)
    return best_score, best


def _distinct(entries):
    """Entries that really are different answers.

    The same label read on the same page at the same position is one
    entry duplicated, not an ambiguity -- abstaining on that would be
    abstaining on nothing.
    """
    seen, out = set(), []
    for entry in entries:
        key = (screen_mod.normalize(entry.get("label", "")),
               entry.get("page"), entry.get("screen_index"),
               entry.get("value"))
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def _where(entry, data):
    for page in data.get("pages", ()):
        if page.get("page_id") == entry.get("page"):
            return page
    return None


def _describe(entry, data):
    page = _where(entry, data) or {}
    place = page.get("screen") or "?"
    if page.get("submenu"):
        place += f"/{page['submenu']}"
    return (f"{entry.get('label')!r} em {place}, screenful "
            f"{entry.get('screen_index')}")


def _verify(reading, page):
    """Is this the page the index said? (CA-F4.8)

    Two independent checks, either of which failing is a refusal to read:
    the perception engine's own `screen_id`, when the index recorded one,
    and a declared spelling of the page's screen/submenu being on screen.
    Reading the wrong page would produce a value that looks perfectly
    fine and is about something else -- the exact failure mode this whole
    project is built to avoid.
    """
    expected_id = page.get("screen_id")
    full = getattr(reading, "full", None) or {}
    actual_id = screen_mod.screen_id(full) if full else None
    if expected_id and actual_id and expected_id != actual_id:
        return False, (f"a tela alcançada tem screen_id {actual_id!r}, mas o "
                       f"índice registrou {expected_id!r} para a página "
                       f"{page.get('page_id')!r}")

    canonical = page.get("submenu") or page.get("screen")
    try:
        spellings = labels.screen(canonical)
    except labels.UnknownLabel:
        return True, None
    texts = [line["text"] for line in lines_of(reading)]
    if any(screen_mod.match_score(spellings, text) for text in texts):
        return True, None
    return False, (f"não confirmei estar em {canonical!r}: nenhuma grafia "
                   f"declarada ({spellings}) está na tela alcançada")


def _read_value(reading, label):
    """The value to the right of `label` on the current screen."""
    full = getattr(reading, "full", None) or {}
    if full:
        found = screen_mod.field_value(full, [label])
        if found is not None:
            return found.label, found.value, found.row

    # A fake session or a legacy reading has no contract to pair over;
    # fall back to the flat lines, matching the label and taking the text
    # to its right on the same row.
    lines = lines_of(reading)
    for line in lines:
        if not screen_mod.match_score([label], line["text"]):
            continue
        centre = line["bbox"]["top"] + line["bbox"]["height"] / 2
        right = [
            other for other in lines
            if other is not line
            and other["bbox"]["left"] > line["bbox"]["left"]
            and abs((other["bbox"]["top"] + other["bbox"]["height"] / 2) - centre)
            <= max(other["bbox"]["height"], line["bbox"]["height"])
            * screen_mod.ROW_TOLERANCE
        ]
        right.sort(key=lambda o: o["bbox"]["left"])
        row = " ".join([line["text"]] + [o["text"] for o in right])
        return line["text"], (right[0]["text"] if right else None), row
    return None, None, None


def _find_setting(tool, session, args, mode):
    args = args or {}
    term = (args.get("term") or "").strip()
    question = (args.get("question") or "").strip() or None

    if not term:
        return ToolResult(
            tool=tool.name, ok=False,
            error="faltou o parâmetro obrigatório 'term' (o nome do ajuste "
                  "procurado, ex.: --term \"Fast Boot\")",
        )

    # First, before anything else and before a single key is sent.
    verb = write_request(term, question)
    if verb:
        return ToolResult(
            tool=tool.name, ok=False, kind="field", value=None,
            error=READ_ONLY_REFUSAL,
            notes=[f"verbo de alteração detectado: {verb!r}",
                   "nenhuma tecla foi enviada à máquina"],
        )

    try:
        data = index_mod.load()
    except index_mod.IndexMissing as e:
        return ToolResult(tool=tool.name, ok=False, error=str(e))
    except index_mod.IndexInvalid as e:
        return ToolResult(
            tool=tool.name, ok=False,
            error=f"índice de rótulos inválido: {e}. Rode o tour de F3 "
                  f"novamente (py -3.13 study_label_index.py) -- não vou "
                  f"responder a partir de um índice que não posso verificar.",
        )

    scope = index_mod.coverage(data)
    score, candidates = search(data, term)
    candidates = _distinct(candidates)

    if not candidates:
        return ToolResult(
            tool=tool.name, ok=True, kind="field", value=None, label=term,
            notes=[f"{NOT_EXIST}: {term!r}", scope["text"],
                   "resposta vinda do índice, sem enviar nenhuma tecla"],
        )

    if len(candidates) > 1:
        return ToolResult(
            # Candidates go in `notes`, not in `abstentions`:
            # `abstentions` carries the perception engine's own E7
            # abstentions everywhere else in this codebase, and putting
            # strings of a different meaning into the same list would
            # make it impossible for a consumer to know what it is
            # reading. The refusal to choose is narrated instead.
            tool=tool.name, ok=True, kind="field", value=None, label=term,
            notes=[f"não vou escolher entre candidatos empatados para "
                   f"{term!r} (score {score}): "
                   + "; ".join(_describe(c, data) for c in candidates),
                   "diga qual deles você quer e eu leio esse",
                   scope["text"]],
        )

    entry = candidates[0]
    page = _where(entry, data)
    if page is None:
        return ToolResult(
            tool=tool.name, ok=False,
            error=f"índice inconsistente: a entrada {entry.get('label')!r} "
                  f"aponta para a página {entry.get('page')!r}, que não existe",
        )

    steps = 0
    sub = page.get("submenu")
    if sub:
        reason = submenu_mod.skip_reason(sub)
        if reason:
            return ToolResult(
                tool=tool.name, ok=True, kind="field", value=None,
                label=entry.get("label"),
                notes=[_describe(entry, data),
                       f"{entry.get('label')!r} está registrado em {sub!r}, "
                       f"mas esse submenu não é navegável automaticamente "
                       f"({reason})",
                       "promover a grafia a CONFIRMADO em biostools/labels.py "
                       "é revisão humana -- não vou navegar por palpite",
                       scope["text"]],
            )
        arrival = submenu_mod.enter_submenu(session, sub, mode=mode)
        steps += arrival.steps
        if not arrival.ok:
            return ToolResult(
                tool=tool.name, ok=False, steps=steps,
                error=f"{entry.get('label')!r} está no índice (página "
                      f"{page['page_id']!r}), mas não consegui chegar lá: "
                      f"{arrival.reason} -- {arrival.detail}",
            )
    else:
        outcome, _ = enter_main_menu_screen(session, page["screen"], mode=mode)
        steps += outcome.steps
        if not outcome.ok:
            return ToolResult(
                tool=tool.name, ok=False, steps=steps,
                error=f"{entry.get('label')!r} está no índice (página "
                      f"{page['page_id']!r}), mas não consegui chegar lá: "
                      f"{outcome.reason}"
                      + (f" ({outcome.detail})" if outcome.detail else ""),
            )

    ok, detail = reposition(session, page, entry["screen_index"])
    steps += page.get("total_screens", 1) + 2 + entry["screen_index"]
    if not ok:
        return ToolResult(tool=tool.name, ok=False, steps=steps, error=detail)

    reading = session.read_stable()
    ok, detail = _verify(reading, page)
    if not ok:
        return ToolResult(
            tool=tool.name, ok=False, steps=steps,
            error=f"verificação de tela falhou antes de ler {entry['label']!r}: "
                  f"{detail} -- não vou devolver um valor lido da tela errada",
        )

    label, value, row = _read_value(reading, entry["label"])
    full = getattr(reading, "full", None) or {}
    common = {
        "tool": tool.name, "steps": steps,
        "screen_id": screen_mod.screen_id(full) if full else None,
        "abstentions": screen_mod.selection_abstentions(full) if full else [],
    }

    if label is None:
        return ToolResult(
            ok=False, kind="field",
            error=f"cheguei na página {page['page_id']!r}, screenful "
                  f"{entry['screen_index']}, mas {entry['label']!r} não está "
                  f"nela agora -- o índice pode ter envelhecido; rode o tour "
                  f"de F3 novamente",
            **common)

    notes = [f"lido em {page['screen']}"
             + (f"/{page['submenu']}" if page.get("submenu") else "")
             + f", screenful {entry['screen_index']} (índice de "
               f"{data.get('captured_at')})"]
    if value is None:
        notes.append(f"achei {label!r} mas nada à direita dele -- é uma "
                     f"entrada de menu, não um par rótulo/valor")

    return ToolResult(ok=True, kind="field", label=label, value=value,
                      raw_value=value, row=row, notes=notes, **common)


FIND_SETTING = register(Tool(
    name="find_setting",
    question=(
        "Procura QUALQUER ajuste da BIOS pelo nome e le o valor dele, "
        "usando o indice de rotulos colhido desta maquina. Use esta tool "
        "quando nenhuma outra tool nomeada responde a pergunta. Ela sabe "
        "sozinha em que tela o ajuste mora -- nao e preciso dizer. Se o "
        "ajuste nao existe nesta BIOS, ela responde exatamente isso, e "
        "isso e uma resposta correta, nao uma falha. Ela e SOMENTE "
        "LEITURA: pedidos para mudar uma configuracao sao recusados."
    ),
    reader=None,
    router=_find_setting,
    restore=False,
    params={
        "term": {
            "type": "string",
            "description": ("Nome do ajuste procurado, o mais proximo "
                            "possivel de como a BIOS o escreve -- ex.: "
                            "'Fast Boot', 'Network Stack', 'BIOS Version'."),
        },
        "question": {
            "type": "string",
            "description": ("A pergunta original do operador, palavra por "
                            "palavra. Opcional, usada para diagnostico e "
                            "para a guarda de somente-leitura."),
        },
    },
))

# `term` is required, `question` is not. `Tool.params` feeds
# `assistant._tool_schemas`, which marks EVERY property required -- right
# for every tool so far, wrong here, so the schema is corrected in place
# rather than by making the assistant guess which parameters are optional.
FIND_SETTING.required_params = ["term"]
