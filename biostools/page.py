"""Reading a WHOLE BIOS page, not just the screenful that happens to fit.

Every reader before this one (`registry.AllFields`) answers with what one
frame shows. Measured live 2026-08-24 on the Positivo's Main page: 73
unique content lines against ~31 visible at once, so a single-frame read
silently returns a third of the page and reports no doubt about it. That
is the failure shape this project treats as the worst one -- confidently
incomplete rather than loudly uncertain.

This module consolidates the mechanism `study_scroll_map.py` proved on
real hardware, so it stops being study code:

* **PgDn/PgUp move a whole screenful and stop dead at the ends.** Rolling
  past an end is harmless, which is what makes "press PgUp more times
  than the page could possibly need" a legitimate way to normalise the
  position instead of tracking where the page currently sits.
* **The end is a repeated signature, never a press count.** A fixed
  number of PgDns is wrong in both directions: too few truncates in
  silence, too many wastes seconds per page on a machine that has to
  answer in a demo.
* **The signature ignores text that changes on its own.** A ticking clock
  or a fan RPM makes two reads of the SAME position look different, which
  reads as "still scrolling" and never terminates -- observed for real,
  the only delta between two reads of the page bottom being
  `10:02:09` -> `10:02:12`.

**The load-bearing detail: a bbox is only valid at the scroll position it
was captured at.** 'Access Level' at y=592 on screenful 3 is a different
row at y=592 on screenful 0. So nothing here ever hands out a coordinate
without the `screen_index` it belongs to, and `reposition()` is the only
sanctioned way to make a stored `screen_index` usable again.

Read-only throughout: `pageup`/`pagedown` are both in `registry.SAFE_KEYS`
and this module sends nothing else.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import screen as screen_mod
from .navigate import SIDEBAR_MAX_X_RATIO

# Generous ceiling on how many screenful one page can hold. Real pages on
# this BIOS settle at 4-5; 12 leaves room for a longer one without ever
# turning a mis-detected end into an unbounded loop.
MAX_SCREENS = 12

# Extra PgUps sent past what the page could need, when normalising to the
# top. Two, not one: a single spare press assumes the caller's idea of how
# tall the page is cannot be off by more than zero, and being at the top
# is the precondition every index in this module is counted from.
NORMALISE_MARGIN = 2

# How much of a recorded signature must still be on screen for a
# repositioning to count as "same place". Not equality: two captures of
# one screen differ by a glyph or two of OCR damage as a matter of course
# (measured on this BIOS -- 'Advanced' read back as 'Avanced'), and exact
# comparison would report a healthy index as stale. 0.70 sits far above
# OCR noise and far below what two DIFFERENT screens of the same page
# share (chrome only: 'Previous', 'Defaults', 'Save & Exit').
SIGNATURE_OVERLAP = 0.70

# Named so a caller can branch on it instead of matching on message text.
STALE_INDEX = "INDICE_DESATUALIZADO"


@dataclass
class ScreenSlice:
    """One screenful of a page, at one scroll position.

    `lines` keep the bbox they were seen with AT THIS `index` and nowhere
    else -- see the module docstring.
    """
    index: int
    signature: set
    lines: list = field(default_factory=list)
    # Label->value pairs for THIS screenful. Computed while the reading is
    # still in hand, because pairing is much better done over a perception
    # contract (which knows groups and classes, so the right-hand icon
    # column is excluded) than over bare boxes -- see `_pairs_of` for the
    # fallback and why it is only a fallback.
    pairs: dict = field(default_factory=dict)


@dataclass
class PageScan:
    """A whole page, screenful by screenful.

    `truncated` is True only when the scan stopped because it hit
    `max_screens` without ever seeing a repeated signature -- i.e. the
    page may hold more than what is here. It is never left False after an
    incomplete read, and `notes` always says so in words as well, because
    a bool nobody looks at is not a warning.
    """
    screens: list = field(default_factory=list)
    truncated: bool = False
    notes: list = field(default_factory=list)
    ok: bool = True
    error: str | None = None
    # The last reading taken while scanning, kept so a caller that needs
    # the perception contract of this page (the tour, to record the page's
    # `screen_id`) does not have to pay for another read right after the
    # scan already took several.
    last_reading: object = None

    @property
    def total_screens(self):
        return len(self.screens)

    def signatures(self):
        """`{screen_index: sorted signature}` -- the shape `PageRecord`
        stores on disk so `reposition` can verify from a file."""
        return {s.index: sorted(s.signature) for s in self.screens}

    def all_lines(self):
        """Every content line seen, each carrying its `screen_index`."""
        out = []
        for slice_ in self.screens:
            for line in slice_.lines:
                item = dict(line)
                item["screen_index"] = slice_.index
                out.append(item)
        return out

    def unique_lines(self):
        """Deduplicated line texts, first occurrence wins.

        A line visible in two consecutive screenful (the overlap a
        page-at-a-time scroll leaves) is one line of the page, not two.
        Keeping the FIRST occurrence keeps its `screen_index` the earliest
        position the line can be read at, which is also the cheapest one
        to scroll back to.
        """
        seen, out = set(), []
        for line in self.all_lines():
            key = screen_mod.normalize(line["text"])
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(line)
        return out

    def pairs(self):
        """Aggregated label->value pairs for the whole page.

        Deduplicated by normalised label, first occurrence winning, and
        each value carries the `screen_index` it was read at:
        `{label: {"value": ..., "screen_index": n}}`.
        """
        out = {}
        for slice_ in self.screens:
            for label, value in slice_.pairs.items():
                if screen_mod.normalize(label) in {screen_mod.normalize(k)
                                                   for k in out}:
                    continue
                out[label] = {"value": value, "screen_index": slice_.index}
        return out


def lines_of(reading):
    """Text lines with a bbox, out of whatever shape the caller has.

    Three shapes reach this module and all three are legitimate: a
    `session.Reading` (what `read_stable` returns), a raw perception
    `full` view, and the legacy OCR dict `read_cursor`/`FakeBios` serve.
    Normalising here rather than at each call site is what lets F1 be
    driven by a fake session in the offline suite and by the real
    pipeline on hardware without two code paths -- and two code paths
    through a scroll loop is exactly how a study becomes untestable.
    """
    full = getattr(reading, "full", None)
    if full is None and isinstance(reading, dict):
        full = reading.get("full")
    if full is None and isinstance(reading, dict) and "primitives" in reading:
        full = reading

    if full is not None:
        out = []
        for prim in full.get("primitives", ()):
            text = (prim.get("content") or "").strip()
            if not text:
                continue
            g = prim.get("geometry") or {}
            out.append({"text": text, "bbox": {
                "left": g.get("x", 0), "top": g.get("y", 0),
                "width": g.get("w", 0), "height": g.get("h", 0)}})
        return out

    if isinstance(reading, dict):
        return [{"text": line["text"].strip(), "bbox": dict(line["bbox"])}
                for block in reading.get("blocks", ())
                for line in block.get("lines", ())
                if line.get("text", "").strip()]
    return []


def _surface_width(reading, lines):
    """Frame width for this reading, or the rightmost text as a stand-in.

    Same reason `navigate.sidebar_limit` scales rather than trusting the
    absolute 300px: SIDEBAR_MAX_X was measured on the 1280x720 HDMI feed,
    and the 3840-wide photographs in `captures/` put the whole sidebar to
    the right of it, which would classify every sidebar line as content.
    """
    frame = None
    if isinstance(reading, dict):
        frame = reading.get("frame")
    else:
        frame = getattr(reading, "frame", None)
    if frame is not None and getattr(frame, "size", 0):
        return frame.shape[1]

    full = getattr(reading, "full", None)
    if full is None and isinstance(reading, dict):
        full = reading.get("full") or (reading if "primitives" in reading else None)
    if full:
        surface = full.get("surface") or {}
        if surface.get("width"):
            return int(surface["width"])

    return max((l["bbox"]["left"] + l["bbox"]["width"] for l in lines), default=0)


def content_lines(reading):
    """Content-panel lines only.

    The sidebar does not scroll with the page, so its lines are identical
    in every screenful. Including them would make two different scroll
    positions look partly the same -- diluting the end-of-page test -- and
    would put menu entries into a page's label index as if they were rows
    of it.
    """
    lines = lines_of(reading)
    width = _surface_width(reading, lines)
    limit = width * SIDEBAR_MAX_X_RATIO if width else SIDEBAR_MAX_X_RATIO * 1280
    return [l for l in lines if l["bbox"]["left"] >= limit]


def is_volatile(text):
    """Text that changes with no keypress involved: clocks, RPM, temps.

    `digits * 2 >= len(text)` -- the same cut `study_menu_tour.py` uses,
    kept identical on purpose so a fingerprint taken by the tour and a
    signature taken here mean the same thing.
    """
    text = (text or "").strip()
    if not text:
        return True
    digits = sum(c.isdigit() for c in text)
    return digits * 2 >= len(text)


def stable_signature(lines):
    """What this screenful shows, minus anything that moves on its own."""
    return {l["text"].strip() for l in lines
            if l["text"].strip() and not is_volatile(l["text"])}


def signature_overlap(recorded, current):
    """Fraction of `recorded` still present in `current`.

    Directional on purpose: the question is "is what I wrote down still
    here", not "are these the same set". A current reading that picked up
    an extra line (a tooltip, a sensor row that woke up) has not moved.
    """
    recorded = {s for s in recorded if s}
    if not recorded:
        return 0.0
    return len(recorded & set(current)) / len(recorded)


def normalise_to_top(session, max_screens=MAX_SCREENS):
    """PgUp far enough that the page cannot be anywhere but the top.

    Counted from `max_screens`, not from where the page is believed to
    be, because believing is exactly what goes wrong: an earlier version
    of `scan_page` mapped from wherever it found the page and returned a
    partial map with no sign that it had -- five screens and 73 lines on
    the first run, one screen and 25 on the second.
    """
    for _ in range(max_screens + NORMALISE_MARGIN):
        session.press("pageup")


def scan_page(session, max_screens=MAX_SCREENS, on_screen=None):
    """Map the whole page: `PageScan` with one `ScreenSlice` per position.

    Stops when a screenful's stable signature repeats the previous one --
    a non-wrapping content panel simply stops moving at the bottom, so the
    same signature twice IS the end. Never on a press count: the count
    only bounds the loop, and reaching it is reported as truncation rather
    than passed off as a complete page.
    """
    normalise_to_top(session, max_screens=max_screens)

    scan = PageScan()
    previous = None
    for _ in range(max_screens):
        reading = session.read_stable()
        scan.last_reading = reading
        lines = content_lines(reading)
        signature = stable_signature(lines)

        if previous is not None and signature == previous:
            break

        index = len(scan.screens)
        scan.screens.append(ScreenSlice(index=index, signature=signature,
                                        lines=lines,
                                        pairs=pairs_of(reading, lines)))
        if on_screen:
            on_screen(index, lines)
        previous = signature
        session.press("pagedown")
    else:
        scan.truncated = True
        scan.notes.append(
            f"leitura TRUNCADA: parei em {max_screens} screenful sem detectar "
            f"o fim da pagina -- pode haver mais conteudo abaixo do que foi lido"
        )

    if not scan.screens or not any(s.lines for s in scan.screens):
        scan.ok = False
        scan.error = ("nenhuma linha no painel de conteudo desta pagina -- "
                      "nada a mapear")
    return scan


def reposition(session, page, screen_index):
    """Scroll back to a `screen_index` recorded in a `PageRecord`, and
    VERIFY it -- P2 of the specs.

    `page` is the stored record, so `total_screens` and `signatures` come
    off the disk rather than from a guess: how many PgUps normalise a page
    depends on how tall that page is, and what proves arrival is what the
    page looked like at that index when it was mapped.

    Returns `(ok, detail)`. A failure is named `INDICE_DESATUALIZADO`
    because the actionable fact is not "scrolling broke" but "the index no
    longer describes this machine -- re-run the tour". Reading anyway
    would answer with whatever row happens to sit at that position now,
    which is the confidently-wrong outcome R5 exists to forbid.
    """
    total = int(page.get("total_screens", 1))
    recorded = (page.get("signatures") or {}).get(str(screen_index))
    if recorded is None:
        recorded = (page.get("signatures") or {}).get(screen_index)
    if recorded is None:
        return False, (f"{STALE_INDEX}: a pagina {page.get('page_id')!r} nao "
                       f"registra assinatura para o screen_index "
                       f"{screen_index} -- rode o tour de F3 novamente")

    for _ in range(total + NORMALISE_MARGIN):
        session.press("pageup")
    for _ in range(screen_index):
        session.press("pagedown")

    current = stable_signature(content_lines(session.read_stable()))
    overlap = signature_overlap(recorded, current)
    if overlap < SIGNATURE_OVERLAP:
        return False, (
            f"{STALE_INDEX}: cheguei ao screen_index {screen_index} da pagina "
            f"{page.get('page_id')!r} mas so {overlap:.0%} da assinatura "
            f"registrada esta na tela (minimo {SIGNATURE_OVERLAP:.0%}) -- "
            f"o indice envelheceu, rode o tour de F3 novamente"
        )
    return True, None


def find_line(scan, target):
    """`(screen_index, line)` for the best declared-spelling match, or None.

    `target` is a spelling or list of spellings from `labels.py`, never
    free text off the screen, and scoring goes through
    `screen.match_score` -- exact-after-normalisation beats containment,
    because 'Main' is a substring of 'Domain' and a page mapped across
    several screenful simply offers more chances for a loose match to win.

    Returns None rather than the closest line when nothing matches. That
    is the whole point: there is no "nearest" answer here.
    """
    best = None
    for slice_ in scan.screens:
        for line in slice_.lines:
            score = screen_mod.match_score(target, line["text"])
            if score and (best is None or score > best[0]):
                best = (score, slice_.index, line)
    if best is None:
        return None
    return best[1], best[2]


def pairs_of(reading, lines=None):
    """Label->value pairs on this screenful.

    Prefers `screen.field_pairs` over the perception contract whenever
    there is one. That matters and is not just tidiness: the contract
    knows which elements are navigation chrome, so the right-hand icon
    column ('Previous Values', 'Optimized Defaults', 'Save & Exit') is
    excluded. The geometry-only fallback cannot see that column for what
    it is, and measured on the real Boot page it happily paired a line of
    help text with the word 'Defaults' sitting to its right -- a pair that
    means nothing and would enter the index looking like a setting.

    The fallback still exists because a legacy reading (and the offline
    suite's fake session) carries boxes and no contract, and a page read
    that way is better than no page read.
    """
    full = getattr(reading, "full", None)
    if full is None and isinstance(reading, dict):
        full = reading.get("full")
    if full and full.get("primitives"):
        return screen_mod.field_pairs(
            full, exclude_ids=screen_mod.nav_element_ids(full))
    return _pairs_of(content_lines(reading) if lines is None else lines)


def _pairs_of(lines):
    """Label->value pairs within one screenful, by row geometry alone."""
    rows = {}
    for line in lines:
        bbox = line["bbox"]
        centre = bbox["top"] + bbox["height"] / 2
        for key in rows:
            ref = rows[key][0]["bbox"]
            tolerance = max(ref["height"], bbox["height"]) * screen_mod.ROW_TOLERANCE
            if abs(centre - (ref["top"] + ref["height"] / 2)) <= tolerance:
                rows[key].append(line)
                break
        else:
            rows[centre] = [line]

    width = max((l["bbox"]["left"] + l["bbox"]["width"] for l in lines), default=0)
    max_gap = width * screen_mod.MAX_PAIR_GAP_RATIO if width else None

    pairs = {}
    for row in rows.values():
        if len(row) < 2:
            continue
        row = sorted(row, key=lambda l: l["bbox"]["left"])
        label, value = row[0], row[1]
        gap = value["bbox"]["left"] - (label["bbox"]["left"] + label["bbox"]["width"])
        if max_gap is not None and gap > max_gap:
            continue
        text = label["text"].strip()
        if text and text not in pairs:
            pairs[text] = value["text"].strip()
    return pairs


@dataclass
class ScrolledAllFields:
    """Reader: every label->value pair on the page, scrolling to find them.

    The scrolling sibling of `registry.AllFields`. Kept as a separate
    reader rather than another flag on that one because the two answer
    different questions -- AllFields answers "what is on this screen",
    this answers "what is on this page" -- and because this one has a
    `PageScan` to hand back (`last_scan`), which a caller that wants
    positions needs and AllFields has no notion of.
    """
    max_screens: int = MAX_SCREENS

    # A page's label->value pairs prove nothing about WHICH page this is,
    # so navigation must never be skipped on the strength of having read
    # some. Same reasoning as `AllFields.identifies_screen`.
    identifies_screen = False

    def __post_init__(self):
        self.last_scan = None

    def read(self, tool, session, reading, steps):
        from .registry import ToolResult

        scan = scan_page(session, max_screens=self.max_screens)
        self.last_scan = scan
        pairs = scan.pairs()
        values = {label: item["value"] for label, item in pairs.items()}
        # `steps` counts real key presses, and scanning is nothing but key
        # presses: reporting it as free would understate what the tool did
        # to the machine.
        steps += (self.max_screens + NORMALISE_MARGIN) + scan.total_screens

        if not scan.ok or not values:
            return ToolResult(
                tool=getattr(tool, "name", "scrolled_all_fields"), ok=False,
                kind="fields", values={}, steps=steps, notes=list(scan.notes),
                error=scan.error or "nenhum par rotulo/valor nesta pagina",
            )

        last = session.read_stable()
        full = getattr(last, "full", None) or {}
        return ToolResult(
            tool=getattr(tool, "name", "scrolled_all_fields"), ok=True,
            kind="fields", values=values, steps=steps,
            screen_id=screen_mod.screen_id(full) if full else None,
            abstentions=screen_mod.selection_abstentions(full) if full else [],
            notes=list(scan.notes), open_ended=True,
        )
