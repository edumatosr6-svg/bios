"""Reading answers out of a perception contract.

Everything here is pure data over `contract["full"]` -- no camera, no
serial port -- so it can be exercised against the fixtures in `captures/`
without any hardware attached.

Why the *full* view and not the digest: the digest carries no geometry
(so label->value pairing across a two-column table is impossible) and no
`classes` array, while E7 abstentions scope to a **class id**. Resolving
"which group could not be decided" therefore needs the class->group link
that only the full view has -- the same reason `cognition._group_verdicts`
takes `full`.

**`focused` is not `selected`.** E7 emits two different state names from
different channels (`perception/stages/e7_state.py:86-89`):

    S1_background / S2_chroma / S3_polarity -> "selected"   (active tab/page)
    S6_border                               -> "focused"    (keyboard cursor)

Navigation needs `focused`; `cognition.fact_summary()` reports only
`selected` and would report nothing at all for the row the cursor is
actually on. That is why this module resolves the cursor itself instead
of calling into cognition.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# How far apart two primitives' vertical centres may be and still count as
# the same visual row, as a fraction of the reference primitive's height.
# BIOS field tables put the label and its value in two columns far apart in
# x, and OCR emits them as unrelated primitives; only their shared row
# position ties them together. 0.6 carried over from the prototype
# (bios_navigate_demo.py), where it paired real BIOS rows correctly.
ROW_TOLERANCE = 0.6

# State names, kept as constants because the difference between them is the
# single most load-bearing distinction in this module (see module docstring).
FOCUSED = "focused"
SELECTED = "selected"

# Abstentions from this stage are the ones that mean "I could not decide
# what is marked here" -- as opposed to E1's rectification notes, which say
# nothing about selection.
STATE_STAGE = "E7.state"


def normalize(text):
    """Lowercase, alphanumerics only.

    Absorbs the two things that reliably differ between what a BIOS draws
    and what OCR returns: the leading submenu marker ('>>', a chevron glyph
    OCR renders inconsistently) and stray punctuation/spacing. 'Hardware
    Monitor', '>>Hardware Monitor' and '» Hardware  Monitor' all collapse
    to 'hardwaremonitor'.
    """
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def match_score(target, text):
    """2 = exact after normalisation, 1 = target contained in text, 0 = no.

    Containment alone is too loose for short BIOS labels -- normalised
    'main' is a substring of 'domain' -- so callers rank candidates and
    prefer an exact hit rather than taking the first containment.
    """
    a, b = normalize(target), normalize(text)
    if not a or not b:
        return 0
    if a == b:
        return 2
    return 1 if a in b else 0


@dataclass
class Marked:
    """An element carrying a state (focused or selected)."""
    element_id: str
    text: str
    confidence: float
    channels: list = field(default_factory=list)


@dataclass
class Element:
    id: str
    text: str
    geometry: dict
    states: list = field(default_factory=list)


@dataclass
class GroupView:
    """One group of the screen, with the cursor resolved.

    `focused`/`selected` being None is NOT the same as `undetermined`
    being set -- "nothing is marked here" and "I could not tell" are
    different answers, and collapsing them is the failure the architecture
    spec calls the engine's most dangerous (PERCEPTION_PIPELINE_SPEC.md).
    Callers must propagate the distinction rather than falling back to a
    bare None check.
    """
    group_id: str
    hint: str | None
    hint_confidence: float | None
    elements: list = field(default_factory=list)
    focused: Marked | None = None
    selected: Marked | None = None
    undetermined: str | None = None  # abstention reason, if one covers this group

    @property
    def status(self):
        if self.focused is not None:
            return FOCUSED
        if self.selected is not None:
            return SELECTED
        if self.undetermined is not None:
            return "undetermined"
        return "none"

    @property
    def cursor(self):
        """Where the keyboard is, preferring the border-marked cursor over
        the active-page marker. A nav menu reports the active tab as
        `selected`; a list row the cursor sits on reports `focused`. When an
        element carries both (observed live on 'Advanced'), the cursor
        reading is the one navigation must act on.
        """
        return self.focused or self.selected


def _by_id(items):
    return {item["id"]: item for item in items or ()}


def symbolic_primitives(full):
    """Text primitives in reading order (top-to-bottom, left-to-right)."""
    prims = [
        p for p in full.get("primitives", ())
        if p.get("content") and p.get("kind") == "symbolic"
    ]
    return sorted(prims, key=lambda p: (p["geometry"]["y"], p["geometry"]["x"]))


def group_views(full):
    """Every group on the screen, cursor resolved, richest first.

    Ordered by element count descending so a caller that just wants "the
    menu" tends to get the substantive group rather than an incidental
    two-item cluster.
    """
    prims = _by_id(full.get("primitives", ()))
    classes = _by_id(full.get("classes", ()))
    types_by_target = {t["target_id"]: t for t in full.get("types", ())}

    states_by_element = {}
    for state in full.get("states", ()):
        states_by_element.setdefault(state["element_id"], []).append(state)

    # An E7 abstention scopes to a class; the group it belongs to is the
    # unit a caller reasons about, so lift it. Defensive on scope_id already
    # being a group id -- the stage documents class scope, but a None or an
    # unknown id must not raise here.
    undetermined_by_group = {}
    for abstention in full.get("abstentions", ()):
        if abstention.get("stage") != STATE_STAGE:
            continue
        scope = abstention.get("scope_id")
        klass = classes.get(scope)
        group_id = klass["group_id"] if klass else scope
        if group_id:
            undetermined_by_group.setdefault(group_id, abstention.get("reason"))

    views = []
    for group in full.get("groups", ()):
        typing = types_by_target.get(group["id"], {})
        view = GroupView(
            group_id=group["id"],
            hint=typing.get("semantic_hint"),
            hint_confidence=typing.get("hint_confidence"),
            undetermined=undetermined_by_group.get(group["id"]),
        )
        for member_id in group.get("member_ids", ()):
            prim = prims.get(member_id)
            if not prim or not prim.get("content"):
                continue
            states = states_by_element.get(member_id, [])
            view.elements.append(Element(
                id=member_id,
                text=prim["content"],
                geometry=prim["geometry"],
                states=states,
            ))
            for state in states:
                marked = Marked(
                    element_id=member_id,
                    text=prim["content"],
                    confidence=state.get("confidence"),
                    channels=list(state.get("channels", ())),
                )
                if state["name"] == FOCUSED and view.focused is None:
                    view.focused = marked
                elif state["name"] == SELECTED and view.selected is None:
                    view.selected = marked
        view.elements.sort(key=lambda e: (e.geometry["y"], e.geometry["x"]))
        views.append(view)

    views.sort(key=lambda v: len(v.elements), reverse=True)
    return views


def find_group(full, hint=None, containing=None):
    """The best group matching a semantic hint and/or containing a text.

    `hint` is what the engine guessed the group is for ('nav_menu',
    'settings_list'); those guesses carry modest confidence (0.43-0.67
    measured), so `containing` exists as the more reliable selector when a
    caller knows an entry that must be in the group it wants.
    """
    candidates = group_views(full)
    if hint:
        candidates = [v for v in candidates if v.hint == hint]
    if containing:
        scored = []
        for view in candidates:
            best = max((match_score(containing, e.text) for e in view.elements),
                       default=0)
            if best:
                scored.append((best, len(view.elements), view))
        if not scored:
            return None
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return scored[0][2]
    return candidates[0] if candidates else None


def find_element(full, target, group=None):
    """Locate one text primitive by fuzzy match, exact hits winning.

    Searches inside `group` when given, otherwise the whole screen -- a
    value like a temperature reading is often not a member of any group.
    """
    if group is not None:
        pool = [(e.text, e.geometry, e.id) for e in group.elements]
    else:
        pool = [(p["content"], p["geometry"], p["id"]) for p in symbolic_primitives(full)]

    scored = [(match_score(target, text), text, geometry, pid)
              for text, geometry, pid in pool]
    scored = [s for s in scored if s[0] > 0]
    if not scored:
        return None
    scored.sort(key=lambda s: s[0], reverse=True)
    score, text, geometry, pid = scored[0]
    return Element(id=pid, text=text, geometry=geometry)


def row_of(full, element, tolerance=ROW_TOLERANCE):
    """Every text primitive sharing `element`'s visual row, left to right.

    BIOS setting tables are two columns far apart in x; OCR emits the label
    and its value as separate primitives with nothing linking them but
    their shared row. Grouping by vertical-centre proximity is what turns
    'CPU Temperature' and '48 C' back into one readable row -- without it a
    tool finds the label, finds no number attached to it, and reports
    failure on a screen that plainly shows the answer.
    """
    height = element.geometry.get("h") or 1
    centre = element.geometry["y"] + height / 2

    row = []
    for prim in symbolic_primitives(full):
        geom = prim["geometry"]
        prim_centre = geom["y"] + (geom.get("h") or 1) / 2
        if abs(prim_centre - centre) <= height * tolerance:
            row.append((geom["x"], prim["content"]))
    row.sort()
    return [text for _, text in row]


def row_text(full, element, tolerance=ROW_TOLERANCE):
    return " ".join(row_of(full, element, tolerance=tolerance))


@dataclass
class FieldRead:
    """A labelled field read off the screen.

    `value` is what sat to the right of the label; `parsed` is that value
    after an optional pattern. Both are kept, plus the whole row, so a
    caller reporting a number can still show the raw text it came from --
    a BIOS reading that looks implausible is exactly the anomaly this
    system exists to surface, and hiding the source text behind a parsed
    float would bury it.
    """
    label: str
    value: str | None
    parsed: str | None
    row: str


def field_value(full, label, pattern=None, tolerance=ROW_TOLERANCE):
    """Read the value of a labelled field, e.g. 'CPU Temperature' -> '61C'.

    Only primitives starting to the RIGHT of the label's right edge count
    as the value. Vertical proximity alone is not enough: on the real
    Positivo Hardware Monitor screen the 'Setup' logo text sits at x=645
    within 14px of 'CPU Temperature''s row centre (x=1471), so a
    whole-row join yields 'Setup CPU Temperature 61C'. Reading rightward
    from the label drops it without needing a tolerance so tight it would
    start missing genuine values.

    Returns None when the label itself is not on screen -- distinct from a
    FieldRead whose `value` is None, which means the label was found but
    nothing followed it.
    """
    element = find_element(full, label)
    if element is None:
        return None

    label_right = element.geometry["x"] + (element.geometry.get("w") or 0)
    height = element.geometry.get("h") or 1
    centre = element.geometry["y"] + height / 2

    right = []
    for prim in symbolic_primitives(full):
        geom = prim["geometry"]
        if geom["x"] < label_right:
            continue
        prim_centre = geom["y"] + (geom.get("h") or 1) / 2
        if abs(prim_centre - centre) <= height * tolerance:
            right.append((geom["x"], prim["content"]))
    right.sort()

    value = " ".join(text for _, text in right) or None
    parsed = None
    if value and pattern:
        match = re.search(pattern, value, re.IGNORECASE)
        if match:
            parsed = match.group(0).strip()

    return FieldRead(
        label=element.text,
        value=value,
        parsed=parsed,
        row=row_text(full, element, tolerance=tolerance),
    )


def cluster_rows(full, tolerance=ROW_TOLERANCE, items=None):
    """Text primitives grouped into visual rows, top to bottom.

    Each row is ordered left to right. `items` restricts clustering to a
    subset (see `field_pairs`, which clusters one region at a time).

    The row's centre is the running mean of its members, not the first
    member's. Anchoring on whoever arrived first let a tall item drag the
    row's centre away from the line everything else sits on: measured on
    the live Main page, the sidebar's 'Event Log' (31px tall, centre
    291.5) opened a row that then absorbed the value '01.22' (centre
    302.5) while its own label 'EC FW Version' (centre 304.0) fell
    outside the shrinking tolerance and started a row of its own -- so
    that field silently went missing.
    """
    prims = symbolic_primitives(full) if items is None else list(items)
    rows = []
    for prim in prims:
        geom = prim["geometry"]
        height = geom.get("h") or 1
        centre = geom["y"] + height / 2
        for row in rows:
            if abs(centre - row["centre"]) <= row["height"] * tolerance:
                row["items"].append(prim)
                row["centre"] += (centre - row["centre"]) / len(row["items"])
                row["height"] = min(row["height"], height)
                break
        else:
            rows.append({"centre": centre, "height": height, "items": [prim]})

    for row in rows:
        row["items"].sort(key=lambda p: p["geometry"]["x"])
    rows.sort(key=lambda r: r["centre"])
    return [row["items"] for row in rows]


# A value sits beside its label, not on the far side of the screen.
# Measured on captures/positivo_advanced_cpu-overheat.jpg (3840 wide):
# the real pairs 'CPU Temperature'->'61C' and 'CPU Fan Speed'->'3098 RPM'
# span 15% and 17% of the width, while the help box on the right edge
# ('Previous') sits 34% away from the submenu entry it was wrongly being
# paired with. 25% separates them with margin on both sides.
MAX_PAIR_GAP_RATIO = 0.25


def region_of(full):
    """{primitive id: smallest region containing it}, None when in none.

    Smallest wins because regions nest: a whole-screen region and a panel
    both contain the same text, and only the panel says anything useful
    about what that text belongs with.
    """
    regions = sorted(
        full.get("regions", ()),
        key=lambda r: (r["geometry"]["w"] or 0) * (r["geometry"]["h"] or 0),
    )
    placed = {}
    for prim in symbolic_primitives(full):
        geom = prim["geometry"]
        cx = geom["x"] + (geom.get("w") or 0) / 2
        cy = geom["y"] + (geom.get("h") or 0) / 2
        placed[prim["id"]] = None
        for region in regions:
            rg = region["geometry"]
            if (rg["x"] <= cx <= rg["x"] + rg["w"]
                    and rg["y"] <= cy <= rg["y"] + rg["h"]):
                placed[prim["id"]] = region["id"]
                break
    return placed


def field_pairs(full, exclude_ids=frozenset(), max_gap_ratio=MAX_PAIR_GAP_RATIO,
                same_region=True):
    """Every label->value pair the screen shows, as {label: value}.

    A BIOS settings page is a two-column table: leftmost text on a row is
    the label, whatever follows to its right is the value. Rows with a
    single item are prose (help text, titles, the footer) and are skipped.

    Both filters below are load-bearing, and each one catches a case the
    other misses -- measured on two real screens:

    * `same_region` -- on the live 1280x720 Main page the sidebar sits
      only ~220-260px from the content column, well inside any sane gap
      limit, so distance cannot separate them. The engine's own regions
      can: content labels and values share one panel region while the
      sidebar and the right-hand hint box fall outside it. Without this,
      'Advanced' was reported as a label whose value was 'BIOS Version'
      -- which also swallowed the real `BIOS Version` row, so the answer
      the tool exists to give went missing rather than merely gaining a
      bad neighbour.

    * `max_gap_ratio` -- on the 4K Hardware Monitor capture every content
      element falls in one whole-screen region, so regions cannot
      separate them; distance can. See MAX_PAIR_GAP_RATIO.
    """
    width = (full.get("surface") or {}).get("width") or 0
    max_gap = width * max_gap_ratio if width else None
    regions = region_of(full) if same_region else {}

    # Rows are clustered per region, not across the whole screen. "Same
    # row" only means "same field" inside one panel: the sidebar and the
    # content column have different line rhythms (26px vs 36px on the live
    # Main page), and interleaving them let a sidebar entry capture a
    # content value before its own label could reach it.
    panels = {}
    for prim in symbolic_primitives(full):
        if prim["id"] in exclude_ids:
            continue
        panels.setdefault(regions.get(prim["id"]) if same_region else None,
                          []).append(prim)

    pairs = {}
    for panel in panels.values():
        for row in cluster_rows(full, items=panel):
            if len(row) < 2:
                continue
            label, rest = row[0], row[1:]
            if max_gap is not None:
                label_right = label["geometry"]["x"] + (label["geometry"].get("w") or 0)
                rest = [p for p in rest
                        if p["geometry"]["x"] - label_right <= max_gap]
            if not rest:
                continue
            text = " ".join(p["content"] for p in rest).strip()
            if text:
                pairs.setdefault(label["content"].strip(), text)
    return pairs


def nav_element_ids(full):
    """Ids of every entry in a navigation menu, for excluding from pairing."""
    return {e.id for v in group_views(full) if v.hint == "nav_menu"
            for e in v.elements}


# -- legacy cursor path ------------------------------------------------
#
# Navigation reads the cursor through `selection.py` (the pre-perception
# path), not through the perception engine's E7 channels. Measured on this
# hardware, on the same frame:
#
#   perception + rapidocr-openvino  -> cannot see the cursor   0.60s
#   perception + paddleocr          -> sees it                13s
#   selection.py + rapidocr-openvino-> sees it                 0.66s
#
# The engine's S1_background samples the background from the perimeter of
# the OCR box, and the box overshoots the highlight bar by 2-3px (bar
# y=134..151, box y=134..153), so that ring lands on the dark panel and
# every element measures the same background -- deviation 0.00 across the
# whole class. `selection.py` measures colour differently and is unaffected.
#
# This is not a new engine competing with `perception/`: keeping both
# paths is the project's own recorded decision (see
# docs/specs/f-specs/motor-percepcao-interface.md, "Coexistência"), and
# `gui.py` already chooses between them with --legacy. Field reading still
# goes through the contract, where it was validated.


def legacy_cursor(ocr_result, prefer_target=None):
    """The cursor, read from a `selection.py`-annotated OCR result.

    More than one line can be highlighted at once -- on the Positivo BIOS
    the active sidebar tab and the focused list row are both marked. The
    one navigation must follow is the row inside the list being walked,
    so the tie is broken by column population: the settings list has many
    more entries than the sidebar. `prefer_target` overrides that when the
    wanted entry is already on screen, since its own column is by
    definition the right one to track.
    """
    lines = [line for block in ocr_result.get("blocks", ())
             for line in block.get("lines", ())]
    marked = [line for line in lines if line.get("highlighted")]
    if not marked:
        return None
    if len(marked) == 1:
        return marked[0]

    if prefer_target:
        for line in lines:
            if match_score(prefer_target, line["text"]):
                column = line["bbox"]["left"]
                same = [m for m in marked
                        if abs(m["bbox"]["left"] - column) <= COLUMN_TOLERANCE]
                if same:
                    return same[0]

    def column_size(line):
        left = line["bbox"]["left"]
        return sum(1 for other in lines
                   if abs(other["bbox"]["left"] - left) <= COLUMN_TOLERANCE)

    return max(marked, key=column_size)


# How far two lines' left edges may differ and still count as one column.
# Real menu entries in a column vary only a few px in x, while distinct
# columns sit hundreds apart (sidebar x=120 vs content x=428 measured on
# the live 1280x720 capture).
COLUMN_TOLERANCE = 40


def screen_id(full):
    return (full.get("identity") or {}).get("screen_id")


def selection_abstentions(full):
    """The E7 abstentions, i.e. only the ones that bear on what is marked."""
    return [a for a in full.get("abstentions", ()) if a.get("stage") == STATE_STAGE]
