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

from . import list_tools, run_tool
from .registry import UnknownTool

# Read-only, no arguments -- every tool today decides everything from its
# own declaration (route + reader) and the live screen, never from
# caller-supplied parameters. Revisit this shape if a tool ever needs one
# (e.g. "read this specific field") rather than adding parameters nobody
# reads.
def _tool_schemas():
    return [
        {"type": "function", "function": {
            "name": name, "description": question,
            "parameters": {"type": "object", "properties": {}},
        }}
        for name, question in list_tools().items()
    ]


# Rounds of "model requests tools, gets results back" before giving up.
# Bounds a model stuck re-requesting the same reading -- these tools drive
# real hardware and a runaway loop must not run unbounded, even read-only.
MAX_ROUNDS = 4


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


def _verbatim(value, text):
    norm = lambda s: " ".join(str(s).split())
    return norm(value) in norm(text)


def _required_values(calls):
    """Every value a narrated answer must reproduce verbatim, plus whether
    any call returned a listing -- which disqualifies narration outright
    regardless of what the values check finds (see module docstring).
    """
    values, has_entries = [], False
    for call in calls:
        r = call.result
        if r is None or not r.ok:
            continue
        if r.kind == "field":
            values.append(r.value)
        elif r.kind == "fields":
            values.extend(r.values.values())
        elif r.kind == "entries":
            has_entries = True
    return values, has_entries


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
        model=DEFAULT_MODEL, timeout=60):
    """The whole loop: let the model call tools until it can answer, then
    verify what it says before showing it.

    Never raises for "no tool matched" or a tool that found nothing on
    screen -- those are answers, returned in `.answer`. Only an
    unreachable LLM endpoint or a hardware fault (propagated from a tool)
    raises, because those mean the setup is broken rather than that the
    BIOS said something unexpected.
    """
    tools = _tool_schemas()
    messages = [{"role": "user", "content": question}]
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
            try:
                result = run_tool(name, session)
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
    required, has_entries = _required_values(calls)
    verified = (not has_entries
                and all(_verbatim(v, final_text) for v in required))

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
