"""Structured field extraction over raw OCR output, via a local LLM
(Lemonade Server / FastFlowLM running on the factory NPU box).

This is a distinct step *after* OCR, not a replacement for it: OCR stays
the ground truth. The LLM's job is narrow on purpose --

- normalize/clean known BIOS field LABELS (small, predictable vocabulary,
  safe to correct: "Systym Date" -> "System Date")
- group OCR text into label -> value pairs
- copy VALUES verbatim -- never invent, "fix", or complete them. A wrong
  digit in a BIOS version string is exactly the kind of anomaly this
  system exists to catch; a plausible-looking guess would silently hide
  it instead.

Optional/pluggable: if the LLM endpoint isn't reachable, callers should
fall back to just the raw OCR result rather than fail the whole capture.
"""
import json
import urllib.error
import urllib.request

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 13305
DEFAULT_MODEL = "qwen3-it-4b-FLM"

_SYSTEM_PROMPT = """You are extracting structured data from OCR text captured from a computer BIOS/UEFI setup screen. The OCR may contain minor recognition errors.

Rules:
1. Identify label-value pairs (e.g. "BIOS Version: F.31" -> label "BIOS Version", value "F.31"). Labels and values may be on the same line separated by whitespace/colon, or in a two-column layout.
2. You MAY correct obvious OCR typos in LABELS ONLY, using standard BIOS/UEFI terminology (e.g. "Systym Date" -> "System Date").
3. You MUST NOT alter, correct, guess, or complete VALUES in any way. Copy each value exactly as given in the OCR text, even if it looks wrong, incomplete, garbled, or inconsistent (e.g. an implausible date or version). If a value looks cut off, still copy exactly the characters present -- never guess what the rest might be.
4. Ignore lines that are menu items, navigation hints, section headers, or anything with no associated value (e.g. "Main", "Advanced", "F1 Help", "ESC Discard Changes").
5. Respond with ONLY a JSON object of this exact shape, no other text, no markdown code fences:
{"fields": {"<label>": "<value>", ...}}"""


class ExtractionError(Exception):
    pass


def _chat_completion(messages, host=DEFAULT_HOST, port=DEFAULT_PORT,
                      model=DEFAULT_MODEL, temperature=0, timeout=30):
    """POST one chat-completions request and return the assistant's text.

    Shared low-level plumbing for every caller that talks to the local LLM
    (field extraction here, contract narration in cognition.py): the
    endpoint, request shape and error translation are identical, only the
    messages and what's done with the answer differ.

    Raises ExtractionError on any failure, so callers across the codebase
    keep catching one exception type regardless of which LLM-backed
    feature failed.
    """
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    url = f"http://{host}:{port}/api/v1/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ExtractionError(f"could not reach LLM endpoint at {url}: {e}") from e

    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise ExtractionError(f"unexpected LLM response shape: {body}") from e


def extract_fields(ocr_result, host=DEFAULT_HOST, port=DEFAULT_PORT,
                    model=DEFAULT_MODEL, timeout=30):
    """Call the local LLM to turn raw OCR text into label->value fields.

    Returns (fields, unverified): `fields` only contains values that were
    checked to appear verbatim in the source OCR text -- small local LLMs
    are not reliably faithful at copying digits (observed: "2026" silently
    became "20026" on a real run despite an explicit instruction not to
    alter values), so every value is verified mechanically rather than
    trusted. Anything that didn't verify lands in `unverified` instead of
    `fields`, so a downstream consumer never silently gets a corrupted
    value under a name that looks trustworthy.

    Raises ExtractionError on any failure (unreachable endpoint, bad
    response, etc.) -- callers decide whether that's fatal or whether to
    just fall back to the raw OCR result.
    """
    text = ocr_result.get("full_text", "").strip()
    if not text:
        return {}, {}

    content = _chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        host=host, port=port, model=model, timeout=timeout,
    )

    parsed = _parse_json_response(content)
    raw_fields = parsed.get("fields")
    if not isinstance(raw_fields, dict):
        raise ExtractionError(f"LLM response missing a 'fields' object: {content!r}")

    fields, unverified = {}, {}
    for label, value in raw_fields.items():
        if isinstance(value, str) and _appears_verbatim(value, text):
            fields[label] = value
        else:
            unverified[label] = value
    return fields, unverified


def _appears_verbatim(value, source_text):
    """Whitespace-insensitive substring check -- the LLM may reflow
    whitespace across an OCR line break even when it copies the value
    faithfully, so a plain `in` check would over-reject.
    """
    normalize = lambda s: " ".join(s.split())
    return normalize(value) in normalize(source_text)


def _parse_json_response(content):
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise ExtractionError(f"LLM did not return valid JSON: {content!r}") from e
