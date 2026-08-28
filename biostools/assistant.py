"""LLM front end: user question in free text -> tools called -> answer phrased.

Uses the model's native OpenAI-style tool-calling (`qwen3-it-4b-FLM` is
labelled "tool-calling" by the server and was confirmed live 2026-08-21 to
honour the `tools` parameter correctly -- it picked the right single tool
for "qual a temperatura da cpu?" and requested BOTH tools in one turn,
unprompted, for a compound question). This replaced an earlier
prompt-based "reply with JSON naming a tool" design before that design was
ever shipped -- native support turned out to exist, so there was no reason
to hand-roll a worse version of it.

The loop supports **chaining**: a question needing more than one reading
("compara a temperatura da CPU com a versão da BIOS") gets multiple tool
calls, in parallel within a round or across rounds, until the model has
enough to answer. `MAX_ROUNDS` bounds this -- these tools drive real
hardware, and a model stuck re-requesting the same reading forever must
not be allowed to run indefinitely.

**The final composed answer is the dangerous step, confirmed live, not
hypothetical.** Fed back a real BIOS build date ("06/26/2026 16:01:12")
and the model's final sentence read "26/06/2026" -- reordered to
day/month and silently dropped the time. The temperature ("61C") came
back as "61°C" -- harmless reformatting, but caught by the same
literal-substring check, which is why that check does not try to be
clever about which reformatting is "safe": distinguishing "harmless
symbol added" from "date silently reordered" reliably is exactly the kind
of judgment call a small model already failed once on this project (see
`extract.py`'s docstring: 2026 -> 20026 on a live run). Every value from
every tool call used in the conversation must appear verbatim in the
final text, or the whole answer falls back to a deterministic join of the
tools' own verified text -- same discipline as `extract._appears_verbatim`,
applied to a second model call instead of the first.

Menu listings (`kind == "entries"`) disqualify LLM narration entirely,
not just their own value: if any tool call in the conversation returned a
list of options, the final answer is always the deterministic join. A
verified walk's list has no single "value" substring to check a
paraphrase against, so a model summarising it could drop or invent an
entry with nothing here to catch it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from extract import DEFAULT_HOST, DEFAULT_MODEL, DEFAULT_PORT, ExtractionError

from . import all_tools, run_tool
from .registry import UnknownTool

# Read-only. Most tools decide everything from their own declaration
# (route + reader) and the live screen, never from caller-supplied
# parameters -- those get `properties: {}` below, same as always. A
# router-based tool (`goto_screen`) is the one exception: it needs the
# caller (the model) to say WHICH screen, so its `Tool.params` is handed
# through as this function call's JSON-schema properties instead of being
# ignored. Everything required is required; nothing here silently accepts
# an argument a tool would then throw away.
def _tool_schemas():
    schemas = []
    for name, tool in all_tools().items():
        schemas.append({"type": "function", "function": {
            "name": name, "description": tool.question,
            "parameters": {
                "type": "object",
                "properties": tool.params,
                "required": (getattr(tool, "required_params", None)
                             or list(tool.params)),
            },
        }})
    return schemas


# Rounds of "model requests tools, gets results back" before giving up.
# Bounds a model stuck re-requesting the same reading -- these tools drive
# real hardware and a runaway loop must not run unbounded, even read-only.
MAX_ROUNDS = 4

# There was no system prompt here at all until 2026-08-28: the model got
# the bare question and a JSON dump of the tool result, with nothing said
# about how to answer. That is a lot to leave to a 4B model, and it showed
# -- asked "o fast boot esta desabilitado ou habilitado?" it relayed the
# whole five-field screen instead of answering the yes/no actually asked.
# The tool had worked, the routing had worked; only the phrasing step had
# no instructions.
#
# Rule 2 is not politeness, it is what keeps the verification in `_finish`
# from rejecting a correct answer: a narration that never mentions the
# value it is reporting cannot be checked against the screen, so it falls
# back to the raw dump even when it was right. Telling the model to cite
# the value is the cheapest way to make "verifiable" and "readable" the
# same sentence rather than competing goals.
#
# Rule 4 exists because the opposite failure is worse than a clumsy
# answer: a model that fills a gap in a reading with something plausible
# produces exactly the silent, confident error this whole project is
# built to prevent (see extract.py: 2026 -> 20026, live).
_SYSTEM_PROMPT = """Você responde perguntas sobre a tela de uma BIOS, usando as tools disponíveis para ler a máquina real.

Regras:
1. Responda DIRETAMENTE o que foi perguntado, em português, numa frase completa. Se a pergunta é de sim/não ("o fast boot está habilitado?"), comece por "Sim" ou "Não".
2. A frase tem que se sustentar sozinha: nomeie o campo e cite o valor lido EXATAMENTE como a tool devolveu (ex.: "Enabled", "61C", "06/26/2026 16:01:12"), sem reformatar, traduzir ou reordenar o valor em si. Ex.: "Sim, o Fast Boot está Enabled." Uma resposta de uma palavra só ("Habilitado") não serve -- quem lê depois não sabe de qual campo era.
3. Não liste os outros campos da tela que não foram perguntados. A tool pode ler a tela inteira; a resposta é só sobre o que o usuário pediu.
4. Se a tool não trouxe o campo perguntado, diga isso claramente. Nunca invente, estime ou complete um valor que não foi lido."""


class RoutingError(Exception):
    """The model's tool choice could not be honoured -- distinct from a
    tool running and finding nothing, which is not an error."""


@dataclass
class ToolCall:
    """One tool invocation made while answering a question, kept for
    audit -- so a caller can see exactly what ran and in what order,
    not just the final text.
    """
    tool: str
    result: object = None    # ToolResult, or None if the name was unknown
    error: str | None = None


@dataclass
class AssistantAnswer:
    question: str
    calls: list = field(default_factory=list)   # ToolCall, in call order
    answer: str = ""
    narrated: bool = False   # True only if the model's own final sentence passed verification
    error: str | None = None

    def as_dict(self):
        return {
            "question": self.question,
            "calls": [{"tool": c.tool, "result": c.result.as_dict() if c.result else None,
                       "error": c.error} for c in self.calls],
            "answer": self.answer, "narrated": self.narrated,
            "error": self.error,
        }


# A closed, declared table -- same discipline as labels.py, not a general
# translator -- for the one class of value where a faithful PT-BR
# narration can never be byte-identical to the English screen text: a
# BIOS toggle field. Confirmed live 2026-08-28: asked "o fast boot esta
# habilitado?", the model correctly answered in Portuguese ("sim, esta
# habilitado") and the plain verbatim check rejected it for not
# containing the literal English word "Enabled", falling back to the raw
# five-field dump on every such question -- not the module docstring's
# "model reworded/altered a number" risk this check exists to catch, just
# the model doing the translation it was asked to do. A temperature or a
# date is never in this table, so that protection is untouched: "61C"
# still has to appear as "61C", not as some accepted "close enough" text.
_VALUE_SYNONYMS = {
    "enabled": ("habilitado", "habilitada", "ativado", "ativada", "ativo", "ativa"),
    "disabled": ("desabilitado", "desabilitada", "desativado", "desativada",
                "inativo", "inativa"),
    "on": ("ligado", "ligada"),
    "off": ("desligado", "desligada"),
    "yes": ("sim",),
    "no": ("nao", "não"),
}


def _verbatim(value, text):
    norm = lambda s: " ".join(str(s).split())
    if norm(value) in norm(text):
        return True
    synonyms = _VALUE_SYNONYMS.get(norm(value).lower())
    if not synonyms:
        return False
    lowered = norm(text).lower()
    return any(syn in lowered for syn in synonyms)


def _required_values(calls):
    """What a narrated answer must reproduce verbatim, split two ways.

    `values` are checked with ALL-must-appear: a single field the caller
    asked for by name (`kind == "field"`), or a short caller-picked list
    (`Fields`, `open_ended=False`) -- short because the question already
    named exactly what matters, so the narration has no excuse to drop
    one.

    `open_groups` are checked with ANY-must-appear, one entry per
    open-ended read (`AllFields`, `open_ended=True`, e.g. `goto_screen`
    landing on a whole screen it does not know the relevant field of in
    advance). Forcing every value from a dozen unrelated fields into the
    narration -- the old, single ALL-must-appear rule -- made concise
    answers to a specific question (e.g. "is Fast Boot on?", landing five
    fields including 'BIOS POST Logo Delay') impossible to narrate: the
    model correctly answers with just the one relevant value, and the old
    check rejected that for not also repeating the other four, falling
    back to the raw dump every time. ANY-must-appear keeps the actual
    protection this exists for -- an answer that echoes NONE of what the
    screen showed is still rejected -- without demanding an unrelated
    field be recited to prove a claim about a different one.

    Also reports whether any call returned a listing, which disqualifies
    narration outright regardless of what either check finds (see module
    docstring).
    """
    values, open_groups, has_entries = [], [], False
    for call in calls:
        r = call.result
        if r is None or not r.ok:
            continue
        if r.kind == "field":
            values.append(r.value)
        elif r.kind == "fields":
            if r.open_ended:
                if r.values:
                    open_groups.append(list(r.values.values()))
            else:
                values.extend(r.values.values())
        elif r.kind == "entries":
            has_entries = True
    return values, open_groups, has_entries


def _deterministic_answer(calls):
    if not calls:
        return "Não tenho uma forma de responder isso ainda -- nenhuma das tools disponíveis cobre essa pergunta."
    parts = []
    for call in calls:
        if call.error:
            parts.append(f"{call.tool}: {call.error}")
        else:
            parts.append(call.result.as_text())
    return "\n".join(parts)


def ask(question, session, host=DEFAULT_HOST, port=DEFAULT_PORT,
        model=DEFAULT_MODEL, timeout=60, nav_mode="keyboard"):
    """The whole loop: let the model call tools until it can answer, then
    verify what it says before showing it.

    `nav_mode` is the operator's choice of how any tool the model picks
    drives sidebar navigation -- "keyboard", "mouse", or "auto" -- passed
    straight through to every `run_tool` call this loop makes.

    Never raises for "no tool matched" or a tool that found nothing on
    screen -- those are answers, returned in `.answer`. Only an
    unreachable LLM endpoint or a hardware fault (propagated from a tool)
    raises, because those mean the setup is broken rather than that the
    BIOS said something unexpected.
    """
    tools = _tool_schemas()
    messages = [{"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": question}]
    calls = []

    for _ in range(MAX_ROUNDS):
        try:
            # Not `extract._chat_completion`: that helper returns only
            # `message.content`, which is enough for the plain-text path
            # but drops `tool_calls` -- a different field of the same
            # response this loop also needs. Same endpoint, same request
            # shape, one field read instead of the reused helper's one.
            raw = _raw_completion(host, port, model, messages, tools, timeout)
        except ExtractionError as e:
            return AssistantAnswer(question=question, calls=calls,
                                   error=f"chamada ao modelo falhou: {e}")

        message = raw["choices"][0]["message"]
        tool_calls = message.get("tool_calls")

        if not tool_calls:
            final_text = message.get("content") or ""
            return _finish(question, calls, final_text)

        messages.append({"role": "assistant", "tool_calls": tool_calls})
        for tc in tool_calls:
            name = tc["function"]["name"].strip().replace("-", "_")
            # Arguments arrive as a JSON-encoded string, same as every
            # OpenAI-style tool call -- and possibly malformed, since it is
            # the model's own text generation, not a parsed structure the
            # server guarantees. A tool with no `params` (every route-based
            # one) never looks at this, so garbage here only matters for
            # `goto_screen`, which reports it as a normal "faltou o
            # parametro" answer rather than raising.
            raw_args = tc["function"].get("arguments") or "{}"
            try:
                call_args = json.loads(raw_args)
            except json.JSONDecodeError:
                call_args = {}
            try:
                result = run_tool(name, session, mode=nav_mode, args=call_args)
                calls.append(ToolCall(tool=name, result=result))
                tool_content = json.dumps(result.as_dict(), ensure_ascii=False)
            except UnknownTool:
                calls.append(ToolCall(tool=name, error="tool desconhecida"))
                tool_content = json.dumps({"error": "tool desconhecida"})
            messages.append({
                "role": "tool", "tool_call_id": tc["id"], "content": tool_content,
            })

    return AssistantAnswer(
        question=question, calls=calls,
        answer=_deterministic_answer(calls), narrated=False,
        error=f"o modelo nao finalizou em {MAX_ROUNDS} rodadas",
    )


def _finish(question, calls, final_text):
    required, open_groups, has_entries = _required_values(calls)
    verified = (
        not has_entries
        and all(_verbatim(v, final_text) for v in required)
        and all(any(_verbatim(v, final_text) for v in group)
                for group in open_groups)
    )

    if verified and final_text.strip():
        return AssistantAnswer(question=question, calls=calls,
                               answer=final_text.strip(), narrated=True)
    return AssistantAnswer(question=question, calls=calls,
                           answer=_deterministic_answer(calls), narrated=False)


def _raw_completion(host, port, model, messages, tools, timeout):
    """Same endpoint `extract._chat_completion` posts to, kept separate
    because that helper only returns the text content -- this loop also
    needs `tool_calls`, which is a different field of the same response.
    """
    import urllib.error
    import urllib.request

    from extract import ExtractionError

    payload = {"model": model, "messages": messages, "tools": tools,
               "tool_choice": "auto", "temperature": 0}
    url = f"http://{host}:{port}/api/v1/chat/completions"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ExtractionError(f"could not reach LLM endpoint at {url}: {e}") from e
