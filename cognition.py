"""Free-text narration of a perception contract, via the local LLM.

A distinct concern from extract.py, which turns raw OCR text into
verbatim-verified label->value pairs. This module takes the perception
engine's contract -- never raw OCR text, never an image
(PERCEPTION_PIPELINE_SPEC.md section 1.1: the digest is "a unica coisa
que a camada de cognicao enxerga") -- and asks the model to describe, in
its own words, what it understood: which screen this is, what is
selected, and what it is unsure about.

There is no verification step on the model's prose, deliberately. Field
extraction has a narrow, checkable output and earns a mechanical check; a
free-text description has no such ground truth, and the entire point of
this step is for a human to read the prose and judge whether the model
understood the screen at all. Filtering the output would hide exactly the
failure this exists to expose -- so whatever the model says is returned
as-is. What IS verified, and reused rather than re-asked of the model, is
described below.

The prompt is written against the digest that
perception/stages/e10_serialization.py `_digest()` actually emits today,
not against the sketch in VISUAL_FEATURE_SPEC.md section 10.2 (which
shows a KeyValueTable rows/label/value shape the implementation does not
currently produce). If `_digest()` changes shape, this prompt has to
change with it.
"""
import copy
import json

from extract import (
    DEFAULT_HOST,
    DEFAULT_MODEL,
    DEFAULT_PORT,
    ExtractionError,
    _chat_completion,
)


def _group_verdicts(full):
    """{group_id: verdict} for every group with a "selected" state or a
    selection-relevant (E7.state) abstention -- the one fact both
    fact_summary (for a human) and narrate_contract's prompt (for the
    model) need, computed exactly once so the two can never disagree
    about it.

    Resolving an abstention's scope_id (usually a class id) up to the
    group it belongs to needs the class->group link, which only the
    *full* contract carries -- the digest omits classes as an
    implementation/audit-level detail. `full` here is a local Python
    input, not something sent to the LLM; see narrate_contract for how
    the result is folded back into a digest-shaped document instead.
    """
    primitives_by_id = {p["id"]: p for p in full.get("primitives", ())}
    classes_by_id = {c["id"]: c for c in full.get("classes", ())}

    def owning_group(scope_id):
        c = classes_by_id.get(scope_id)
        return c["group_id"] if c else None

    verdicts = {}
    for state in full.get("states", ()):
        if state["name"] != "selected":
            continue
        group_id = owning_group(state["class_id"])
        prim = primitives_by_id.get(state["element_id"])
        if group_id and prim:
            verdicts[group_id] = {
                "status": "selected",
                "text": prim.get("content"),
                "confidence": state["confidence"],
            }

    for abstention in full.get("abstentions", ()):
        if abstention["stage"] != "E7.state":
            continue
        group_id = owning_group(abstention.get("scope_id"))
        # A class that already resolved to "selected" never also abstains
        # (E7.state emits one or the other per class, see
        # perception/stages/e7_state.py) -- setdefault here is a
        # last-writer-loses-safely guard, not a real conflict.
        if group_id:
            verdicts.setdefault(group_id, {
                "status": "undetermined",
                "reason": abstention["reason"],
            })

    return verdicts


def _annotate_with_verdicts(full, digest):
    """Digest, deep-copied, with each group's `selection_status` field
    pre-resolved from `full` via `_group_verdicts`.

    This exists because asking the model to do that resolution itself
    failed on 3/3 real photos across two different local models (4B
    general-instruct and 8B reasoning-distilled) -- both correctly
    *found* the relevant abstention and then, in the same or a later
    sentence, asserted the group was empty anyway (see the removed
    "MANDATORY FIRST STEP" prompt paragraph in git history for the
    attempt at fixing this with instructions alone; it helped but did not
    reliably fix it). An abstention's scope_id -> owning group is a
    precise symbolic lookup, exactly the kind of task small local models
    are unreliable at regardless of general capability. Pre-resolving it
    in Python -- reusing the same code fact_summary already proved
    correct -- removes the lookup from the model's job entirely; what's
    left (report an already-correct fact in fluent prose) is the part
    every test run so far showed the model is actually good at.

    Still digest-shaped, still no raw provenance/descriptor data --
    the architectural boundary (PERCEPTION_PIPELINE_SPEC.md 1.1: the
    digest is the only thing cognition sees) is preserved; `full` is
    consulted locally to compute one field, never forwarded itself.
    """
    verdicts = _group_verdicts(full)
    annotated = copy.deepcopy(digest)
    for region in annotated.get("regions", ()):
        for group in region.get("groups", ()):
            group["selection_status"] = verdicts.get(
                group["id"], {"status": "no_selection_info"}
            )
    return annotated


# The "CRITICAL"/"MANDATORY FIRST STEP" prompt paragraphs from earlier
# versions asked the model to resolve abstention scope_id -> group itself
# before writing prose. Measured against 3 real photos across two models,
# that specific lookup was never reliable -- the model routinely found
# the right abstention and still asserted the group was empty. v3 below
# stops asking: _annotate_with_verdicts precomputes `selection_status` per
# group, and the prompt's job shrinks to reporting it faithfully, which
# testing showed the model is actually good at.
_SYSTEM_PROMPT = """You are describing a computer BIOS/UEFI setup screen to a human reviewer, using ONLY a structured "contract" produced by a perception engine. You have not seen an image and you have not seen raw OCR text -- the contract below is everything you know. It is JSON shaped like this:

- screen: {screen_id, title_text, confidence, quality, rectified} -- the engine's best guess at screen identity. title_text and confidence may be null or low.
- regions: areas of the screen. Each has a structural_type (a FACT, e.g. "Repeater", "KeyValueTable") and contains groups.
- regions[].groups: each has a structural_type, an axis, a cardinality, an OPTIONAL semantic_hint ({value, confidence} -- an OPINION, separate from structural_type, and often absent), a selection_status, and elements.
- regions[].groups[].selection_status -- ALREADY RESOLVED, trust it directly, do not re-derive it from elements or abstentions yourself: {"status": "selected", "text": ..., "confidence": ...} means that exact element is selected; {"status": "undetermined", "reason": ...} means the engine looked and could not decide -- report this as "could not determine", never as "nothing selected"; {"status": "no_selection_info"} means there is nothing to report for that group, and you may say nothing is selected there.
- groups[].elements: each has text (content read from the screen) and state -- present only for elements the engine actually singled out; most elements will have an empty state list, which is normal and not itself notable.
- abstentions: places the engine explicitly declined to decide, listed for completeness. The ones relevant to selection are already reflected in each group's selection_status above -- you do not need to match scope_id to a group yourself. Abstentions here about OTHER things (rectification, cropping, insufficient members to compare) are not pre-summarized; describe those yourself if notable.

Write a short free-text description (a few sentences of plain prose -- no headings, no bullet points, no JSON) covering:
- What screen this appears to be, based on title_text and any semantic_hint values. If neither is present, or both are low-confidence, say you cannot tell rather than guessing.
- What is selected, for every group whose selection_status is "selected" -- name the exact text and confidence.
- For every group whose selection_status is "undetermined": say plainly the engine could not determine the selection there. Do not say nothing is selected, do not omit it, and do not say no abstention applies -- the field already tells you one does.
- Anything else notable: other element states, unusual or low-confidence values, non-selection abstentions and their reasons.
- What you are personally unsure about, and why (a low confidence score, a semantic_hint you are choosing not to trust, and so on).

Ground every claim in the contract. Do not invent element text, labels, screen names, vendors, or BIOS field meanings that are not literally present in it. If you extrapolate beyond what is literally stated (for instance guessing what a screen is used for from its title), say explicitly that you are doing so. If the contract has no regions and no abstentions, say plainly that there is nothing to describe."""


def narrate_contract(contract, host=DEFAULT_HOST, port=DEFAULT_PORT,
                      model=DEFAULT_MODEL, timeout=180):
    """Ask the LLM to describe a perception contract in free text.

    `contract` must be the `{"digest": ..., "full": ...}` dict from
    `Serialisation(view="both")` (or `run_pipeline`'s `.contract`) --
    never a bare digest, never raw OCR text, never an image. `full` is
    used locally to pre-resolve each group's `selection_status` (see
    `_annotate_with_verdicts`) and is not itself sent to the model; only
    the annotated, still digest-shaped document is.

    Returns the model's response unmodified: no parsing, no verification,
    by design (see the module docstring).

    Raises ExtractionError on any failure (unreachable endpoint, bad
    response shape), same discipline as extract_fields -- callers decide
    whether to fall back rather than getting a placeholder string that
    reads like a real answer.

    `timeout` defaults much higher than extract_fields's 30s. The prompt
    itself (system instructions + a ~3KB digest) runs well over a
    thousand tokens, and this NPU measured ~14-16 tok/s on *prefill* --
    that alone can take 1.5-2 minutes before the model emits a single
    output token, before generation time (which also scales with the
    longer prose output here vs. a compact {"fields": {...}}) is even
    counted. A shorter timeout risks raising ExtractionError on a request
    that was simply still being read, not stuck.
    """
    if contract is None:
        raise ValueError("narrate_contract needs a {'digest', 'full'} contract, got None")

    annotated_digest = _annotate_with_verdicts(contract["full"], contract["digest"])

    content = _chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(annotated_digest, indent=2, ensure_ascii=False)},
        ],
        host=host, port=port, model=model, timeout=timeout,
    )
    return content.strip()


def fact_summary(contract):
    """Deterministic, LLM-free account of what's selected vs. undetermined,
    computed straight from the contract -- a fast anchor to check a
    narrate_contract() response against, not a replacement for it. Shares
    `_group_verdicts` with narrate_contract's own input annotation, so
    this and what the model was actually told can never disagree about
    the underlying facts -- only about whether the model reported them
    faithfully, which is the one thing left for a human to judge.

    `contract` must be the *full* view (has classes/groups, which the
    digest omits -- see `_group_verdicts`). Returns a short multi-line
    string, or a one-line "nothing notable" message if no group has a
    selection or a relevant abstention.
    """
    verdicts = _group_verdicts(contract)
    if not verdicts:
        return "fact check (no LLM): no group has a selected element or a selection-relevant abstention."

    lines = ["fact check (no LLM):"]
    for group_id in sorted(verdicts):
        verdict = verdicts[group_id]
        if verdict["status"] == "selected":
            lines.append(
                f"  [{group_id}] SELECTED: {verdict['text']!r} "
                f"(confidence {verdict['confidence']:.2f})"
            )
        else:
            lines.append(f"  [{group_id}] UNDETERMINED: could not decide a selection here ({verdict['reason']})")
    return "\n".join(lines)
