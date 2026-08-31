"""What a "tool" is, and how one runs.

A tool answers one question about the BIOS screen. It is a **declaration**
-- where to go and what to read -- not a program: adding the next tool
should be filling in a `Tool(...)`, never rewriting the navigate/read
loop. Everything a tool needs at runtime comes from the `BiosSession`
handed to it, so one session serves many tools and a tool may call
another.

Every tool exposes both shapes the callers need today:
`Tool.run(session)` for a script or another tool, and a CLI subcommand
(see `__main__.py`) for an operator. The result is structured either way,
so pointing an LLM at it later needs no second output format.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import labels, page as page_mod, screen
from .navigate import (
    activate, enter_main_menu_screen, looks_like_dialog, move_to, walk_group,
)

# Keys a read-only tool is allowed to send. Navigation and escape only --
# no '+'/'-'/F10/'y', which change or commit BIOS settings. This first
# generation of tools observes the machine under test; it must not be able
# to reconfigure it because a route was declared carelessly. Widen this
# deliberately, per tool, if a writing tool is ever wanted.
SAFE_KEYS = frozenset({
    "up", "down", "left", "right", "enter", "esc",
    "pageup", "pagedown", "home", "end", "tab",
})


class UnsafeRoute(ValueError):
    pass


class UnknownTool(KeyError):
    pass


@dataclass
class Step:
    """One leg of the route: put the cursor on `to`, then open it.

    `to` is a **canonical screen name** from `labels.SCREENS`, not the
    text a BIOS draws -- see that module for why the two are separate.
    Resolved eagerly in __post_init__ so a typo fails when the tool is
    declared, at import time, instead of halfway through driving a real
    machine.

    `focus_key`, pressed once before this leg's walk starts, exists
    because arrow keys are scoped to whichever of the screen's regions
    currently holds keyboard focus -- confirmed live on the Positivo BIOS
    (2026-08-21): with focus in the content panel, "down" scrolls through
    that panel's own fields (observed: eight presses walked CPU cache
    figures, never touched the sidebar) and the sidebar's active-tab
    indicator sits still throughout, which reads exactly like a stuck
    detector until you notice nothing else moved either. "left" is what
    hands focus to the sidebar; a small icon beside the on-screen "Setup"
    label changes state when it does, which is how the user watching the
    physical monitor caught what no OCR-based reading here was catching.
    """
    to: str
    hint: str | None = None
    key: str = "down"
    activate: bool = True
    max_steps: int = 20
    focus_key: str | None = None

    def __post_init__(self):
        self.spellings = labels.screen(self.to)


@dataclass
class ToolResult:
    """One answer.

    `kind` says which payload carries it -- `value` for a single field,
    `values` for a set of them, `entries` for a list of menu options. All
    three keys are always present in the JSON so a consumer can rely on
    the shape without branching first.

    `open_ended`, for `kind == "fields"` only: True when `values` is
    whatever a screen happened to show (`AllFields`, e.g. `main_info`,
    `goto_screen`) rather than a short list the caller specifically named
    (`Fields`, e.g. `bios_info`'s three fields). Not part of the public
    JSON shape (`as_dict` below) -- it exists only to tell
    `assistant._required_values` apart: a targeted `Fields` answer is
    short because the question already picked exactly what matters, so
    narrating it should echo every value back; an open `AllFields` dump
    can be a dozen unrelated pairs for a question about ONE of them, and
    demanding all of them appear verbatim in the narration made every
    such answer fall back to the raw dump -- see goto_screen's own
    "fast boot enabled?" report, 2026-08-28.
    """
    tool: str
    ok: bool
    kind: str = "field"
    value: str | None = None
    raw_value: str | None = None
    label: str | None = None
    row: str | None = None
    values: dict = field(default_factory=dict)
    entries: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    screen_id: str | None = None
    steps: int = 0
    error: str | None = None
    abstentions: list = field(default_factory=list)
    open_ended: bool = False

    def as_dict(self):
        return {
            "tool": self.tool, "ok": self.ok, "kind": self.kind,
            "value": self.value, "raw_value": self.raw_value,
            "label": self.label, "row": self.row,
            "values": self.values, "entries": self.entries,
            "notes": self.notes, "screen_id": self.screen_id,
            "steps": self.steps, "error": self.error,
            "abstentions": self.abstentions,
        }

    def as_text(self):
        if not self.ok:
            return f"{self.tool}: sem resposta -- {self.error}"

        if self.kind == "entries":
            lines = [f"{len(self.entries)} opcoes no menu:"]
            lines += [f"  - {e}" for e in self.entries]
        elif self.kind == "fields":
            width = max((len(k) for k in self.values), default=0)
            lines = [f"{len(self.values)} campos lidos:"]
            lines += [f"  {k:{width}s} : {v}" for k, v in self.values.items()]
        else:
            line = f"{self.label or self.tool}: {self.value}"
            if self.raw_value and self.raw_value != self.value:
                line += f"  (lido: {self.raw_value!r})"
            lines = [line]

        lines += [f"  ! {n}" for n in self.notes]
        return "\n".join(lines)


@dataclass
class Field:
    """One value to read, named by concept rather than by screen text.

    `label` is a canonical name from `labels.FIELDS`. Resolved eagerly so
    an unknown concept is caught at import, not on the factory floor.
    """
    label: str
    pattern: str | None = None

    def __post_init__(self):
        self.spellings = labels.field(self.label)


@dataclass
class Fields:
    """Reader: pull specific labelled fields off the screen we landed on.

    `scroll`, off by default (matching every tool before it needed this),
    presses `scroll_key` and re-checks only the specs still missing --
    exists because a settings page can spread its fields across more than
    one screenful, and a spec's label simply is not on the frame the tool
    lands on. Confirmed against `data/label_index.json` (the F3 harvest):
    e.g. 'Product Name'/'Manufacturer Name'/'Serial Number' all sit at
    screen_index 1 on the Main page, one scroll past 'System Time'/'EC FW
    Version' at screen_index 0 -- a tool grouping either set alone is
    fine, but reading past its own screenful without scrolling would
    silently report "not on this screen" forever, on real hardware too,
    not just a stale offline fixture.

    `stall_limit` measures a real dead zone, not a guess. Confirmed live
    2026-08-31 against real hardware (Positivo, BIOS 1.2.5.XD22.I219V.P):
    landing on Main and pressing `scroll_key` twice changes NOTHING
    visible (only the live clock) -- the page only starts actually
    scrolling on the THIRD press. A `stall_limit` of 2 (this reader's
    first version, and still `AllFields._scroll_and_merge`'s) means the
    loop gives up at the exact edge of that dead zone, one press before
    it would have started working -- reproduced live: `ec_info`,
    `product_info`, `memory_info`, `mac_address`,
    `management_engine_info` and every Security/Boot/Advanced field past
    screen_index 0 abstained "not on this screen" on a real, connected
    machine where the field plainly exists a few presses further down.

    The dead zone is not the same size on every page, measured the same
    day: 2 presses on Main, but **6** on Boot -- 'PXE Boot after Wake on
    LAN' and the boot order only turn up on the 8th/9th press, with
    almost nothing new in between. A `stall_limit` tuned to Main's dead
    zone (4) still cut Boot off before it ever reached them. 8 clears the
    worst measured case with margin; `max_scroll` (20) is the hard
    ceiling regardless, so a genuinely absent field costs at most a
    handful of extra presses, never an unbounded search.
    """
    specs: list
    scroll: bool = False
    scroll_key: str = "down"
    max_scroll: int = 30
    stall_limit: int = 8

    # Named labels identify their own screen: 'CPU Temperature' exists on
    # the Hardware Monitor page and nowhere else, so finding it is proof
    # of being on the right page. That lets `Tool.run` skip navigating
    # when the answer is already in front of it.
    identifies_screen = True

    def __post_init__(self):
        if self.scroll and self.scroll_key not in SAFE_KEYS:
            raise UnsafeRoute(
                f"Fields(scroll=True) usaria a tecla {self.scroll_key!r}, "
                f"que nao esta em SAFE_KEYS"
            )
        if self.scroll:
            # The identify-without-navigating shortcut (Tool.run) would
            # otherwise scroll blindly on whatever screen the BIOS happens
            # to be showing BEFORE this tool's own route ever runs -- fine
            # when that guess is right, but a real side effect (cursor
            # left mid-scroll on an unrelated page) when it is not. A
            # scrolling Fields always takes the real route instead, which
            # lands on a known screen_index 0 before it scrolls from there.
            self.identifies_screen = False

    def read(self, tool, session, reading, steps):
        full = reading.full
        values, notes = {}, []
        single = None
        remaining = list(self.specs)

        def scan(full):
            nonlocal single
            still = []
            for spec in remaining:
                found = screen.field_value(full, spec.spellings, pattern=spec.pattern)
                if found is None:
                    still.append(spec)
                    continue
                if not found.value:
                    # On a scrolling read this is not necessarily the real
                    # field -- confirmed live 2026-08-31: 'Intel VT-d'
                    # matched a wrapped HELP-TEXT line ("...support to
                    # Intel VT-d (Intel Virtualization Technology for
                    # Directed I/O)...") on the frame before the real
                    # toggle line scrolled into view. Treating that as
                    # terminal made `virtualization_status` permanently
                    # give up on a field that plainly existed a screenful
                    # later. Keep looking while there is still scrolling
                    # left to do; a single-frame (non-scrolling) read has
                    # nowhere else to look, so there this stays terminal,
                    # same as before.
                    if self.scroll:
                        still.append(spec)
                    else:
                        notes.append(f"achei {found.label!r} mas nada a direita dele")
                    continue
                # `parsed` is None when the pattern did not match: keep the
                # raw text as the answer rather than dropping it. A BIOS
                # value that does not fit the expected shape is exactly the
                # anomaly this system exists to surface.
                values[found.label] = found.parsed or found.value
                single = found
            return still

        remaining = scan(full)

        if self.scroll and remaining:
            # Stall tracks whether the PAGE is still revealing anything
            # new at all -- not whether one of OUR specs showed up yet,
            # and not only whether a new label/value PAIR showed up.
            # Measured live 2026-08-31 why both distinctions matter: on
            # the real Main page, 'MAC Address' first appears at the 6th
            # press and 'ME FW Version' at the 10th, with OTHER content
            # (Product Name, EC Build Date, ...) turning up on every
            # frame in between -- a stall counter watching only THIS
            # reader's own specs gave up long before reaching them, even
            # though the page was plainly still moving. Watching PAIRS
            # (what the first fix used) still wasn't enough on Advanced:
            # 'S.M.A.R.T. Status Check' sits behind several screenfuls of
            # wrapped HELP-TEXT prose that scrolls new RAW TEXT every
            # press without forming a new label/value pair (no value to
            # its right), so a pairs-only signal reads that stretch as
            # stalled and quits mid-page. Raw text lines are the widest
            # honest signal: they change even while scrolling through
            # pure prose, and only truly stop changing at the real end of
            # the page (or a wrap, or a stuck key) -- same content this
            # already reads for `field_value`, just watched as a whole
            # instead of matched piece by piece.
            seen_texts = {l["text"] for l in page_mod.content_lines(reading)}
            stall = 0
            for _ in range(self.max_scroll):
                if not remaining:
                    break
                session.press(self.scroll_key)
                steps += 1
                reading = session.read_stable()
                full = reading.full
                remaining = scan(full)
                current_texts = {l["text"] for l in page_mod.content_lines(reading)}
                new_texts = current_texts - seen_texts
                seen_texts |= current_texts
                if new_texts:
                    stall = 0
                else:
                    stall += 1
                    if stall >= self.stall_limit:
                        break

        notes = ([f"rotulo {s.label!r} nao esta nesta tela (grafias tentadas: "
                  f"{s.spellings})" for s in remaining] + notes)

        common = {
            "tool": tool.name, "steps": steps,
            "screen_id": screen.screen_id(full),
            "abstentions": screen.selection_abstentions(full),
        }

        if not values:
            return ToolResult(ok=False, notes=notes,
                              error="nenhum dos rotulos pedidos foi lido nesta tela",
                              **common)

        if len(self.specs) == 1 and single is not None:
            return ToolResult(
                ok=True, kind="field", label=single.label, row=single.row,
                value=single.parsed or single.value, raw_value=single.value,
                values=values, notes=notes, **common,
            )
        return ToolResult(ok=True, kind="fields", values=values,
                          notes=notes, **common)


@dataclass
class AllFields:
    """Reader: every label->value pair on the screen, without naming them.

    Preferred over listing labels when the question is "what does this
    page say" -- a hardcoded label list silently returns less when a BIOS
    model words a field differently, while this returns whatever is there
    and lets the caller notice.

    `scroll`, when set, does not stop at the first frame: it presses
    `scroll_key` (content is already focused after the ENTER that opened
    this screen -- see `enter_main_menu_screen`'s docstring) and re-reads,
    merging any label the new frame shows that the first one did not,
    same "keep going until nothing new turns up" shape `walk_group` uses
    for a menu. Exists because a settings page can hold more rows than
    fit on screen at once -- confirmed live 2026-08-28: asked "what is
    Boot Option #1", `goto_screen` on 'boot' answered with the five fields
    visible in the first frame and never found it, because it never
    scrolled. Off by default (`False`, matching every reader before this
    one) because it costs real key presses and reads for every screen,
    not just the ones that need it; `goto_screen` turns it on because it
    does not know ahead of time whether the screen it is about to land on
    is one page or several.

    `stall_limit`/`max_scroll`: see `Fields.stall_limit` -- same fix, same
    evidence (2026-08-31, real hardware). The dead zone after landing on
    a page is not the same size everywhere (2 presses on Main, 6 on
    Boot), so a limit tuned to the shortest one cuts pages with a longer
    one off before they ever start revealing what is being searched for.
    """
    exclude_nav: bool = True
    scroll: bool = False
    scroll_key: str = "down"
    max_scroll: int = 30
    stall_limit: int = 8

    # Any settings page has label->value pairs, so reading some proves
    # nothing about *which* page this is. Never skip navigation for this.
    identifies_screen = False

    def __post_init__(self):
        if self.scroll and self.scroll_key not in SAFE_KEYS:
            raise UnsafeRoute(
                f"AllFields(scroll=True) usaria a tecla {self.scroll_key!r}, "
                f"que nao esta em SAFE_KEYS"
            )

    def read(self, tool, session, reading, steps):
        full = reading.full
        exclude = screen.nav_element_ids(full) if self.exclude_nav else frozenset()
        values = screen.field_pairs(full, exclude_ids=exclude)
        notes = []

        if self.scroll:
            values, extra_steps, scroll_notes = self._scroll_and_merge(
                session, values)
            steps += extra_steps
            notes += scroll_notes

        return ToolResult(
            tool=tool.name, ok=bool(values), kind="fields", values=values,
            steps=steps, screen_id=screen.screen_id(full),
            abstentions=screen.selection_abstentions(full), notes=notes,
            error=None if values else "nenhum par rotulo/valor nesta tela",
            open_ended=True,
        )

    def _scroll_and_merge(self, session, values):
        """Press `scroll_key`, re-read, merge in whatever label is new.

        Stops after `stall_limit` consecutive presses that add nothing --
        one could be a redraw quirk, but `stall_limit` in a row means
        either the list ended (a non-wrapping content panel simply stops
        moving, same as the sidebar in
        `navigate.enter_main_menu_screen_by_count`) or it wrapped back to
        labels already merged in. Either way there is nothing left to
        gain by continuing, and stopping early keeps a short page (most
        of them) to the few presses that confirm it, not the full
        `max_scroll` budget.
        """
        values = dict(values)
        notes = []
        steps = 0
        stall = 0

        for _ in range(self.max_scroll):
            session.press(self.scroll_key)
            steps += 1
            reading = session.read_stable()
            full = reading.full
            exclude = screen.nav_element_ids(full) if self.exclude_nav else frozenset()
            found = screen.field_pairs(full, exclude_ids=exclude)
            new = {k: v for k, v in found.items() if k not in values}
            if new:
                values.update(new)
                stall = 0
            else:
                stall += 1
                if stall >= self.stall_limit:
                    break
        else:
            notes.append(
                f"parei de rolar apos {self.max_scroll} teclas -- "
                f"pode haver mais campos abaixo do que os lidos"
            )

        return values, steps, notes


def _in_screen_order(walked, visible):
    """`walked` entries laid out in `visible`'s top-to-bottom order.

    Anything walked but not matched to a visible line is kept at the end
    rather than dropped -- losing a confirmed menu option to a text
    mismatch would be worse than reporting it out of order.
    """
    ordered, used = [], set()
    for text in visible:
        for i, entry in enumerate(walked):
            if i not in used and screen.match_score(text, entry):
                ordered.append(entry)
                used.add(i)
                break
    ordered += [e for i, e in enumerate(walked) if i not in used]
    return ordered


@dataclass
class Entries:
    """Reader: list the options of a menu.

    `walk` moves the cursor through the menu instead of trusting one
    reading. It costs a reading per entry but earns two things a single
    reading cannot give: it excludes text that merely shares the column
    (measured: the `nav_menu` group also contains the 'POSITIVO'/'Setup'
    logo) and it proves each option is actually reachable.

    A failed walk is not a failed tool. The single-reading list is always
    produced, so if the cursor cannot be driven the answer still comes
    back -- flagged in `notes` as unconfirmed rather than thrown away.
    """
    hint: str = "nav_menu"
    walk: bool = True
    focus_key: str | None = None
    max_steps: int = 20

    def read(self, tool, session, reading, steps):
        full = reading.full
        group = screen.find_group(full, hint=self.hint)
        visible = [e.text for e in group.elements] if group else []
        notes = []

        entries = visible
        if self.walk:
            outcome = walk_group(session, hint=self.hint,
                                 focus_key=self.focus_key,
                                 max_steps=self.max_steps)
            steps += outcome.steps
            if outcome.moved:
                # Report in screen order, not walk order. A wrapping menu
                # is entered wherever the cursor happened to be, so the
                # visiting sequence is rotated relative to what a person
                # sees; the single reading knows the real top-to-bottom
                # order, so use it to lay the confirmed entries back out.
                entries = _in_screen_order(outcome.entries, visible)
                skipped = [t for t in visible
                           if not any(screen.match_score(t, e)
                                      for e in outcome.entries)]
                if skipped:
                    notes.append(
                        "texto na coluna em que o cursor nunca pousou "
                        f"(nao e opcao de menu): {', '.join(map(repr, skipped))}"
                    )
                if not outcome.complete:
                    notes.append(f"caminhada incompleta: {outcome.detail}")
            else:
                # The cursor never moved, so nothing was confirmed -- do
                # not let a one-entry walk masquerade as the whole menu.
                notes.append(
                    "nao consegui mover o cursor neste menu"
                    + (f" ({outcome.detail})" if outcome.detail else "")
                    + " -- lista abaixo e so o que a tela mostra, sem confirmacao"
                )
        else:
            notes.append("sem caminhada: lista e so o que a tela mostra")

        return ToolResult(
            tool=tool.name, ok=bool(entries), kind="entries", entries=entries,
            notes=notes, steps=steps, screen_id=screen.screen_id(full),
            abstentions=screen.selection_abstentions(full),
            error=None if entries else f"nenhum menu com hint {self.hint!r} nesta tela",
        )


def _close_opened(session, opened):
    """Send one ESC per level opened -- **looking between each one**.

    The version this replaces sent them back to back without ever
    re-reading the screen. That is unsafe on this BIOS, where ESC at the
    top level does not go up a level but opens 'Discard Changes and Exit'
    with Ok and Cancel. It happened for real twice on 2026-08-24: a tool
    failed mid-route, its cleanup fired, and the machine was left sitting
    on that dialog. Had the loop had one more ENTER to send, it would have
    answered it.

    So: after each ESC, look. If a dialog appeared, send one more ESC to
    dismiss it (confirmed to work on this BIOS) and stop -- never keep
    pressing into a dialog, and never press ENTER to resolve one. A tool
    left one level too deep is a small, self-correcting problem; a tool
    that confirms an exit is not.
    """
    for _ in range(opened):
        session.press("esc")
        if looks_like_dialog(session.read_cursor()):
            session.press("esc")
            return False
    return True


@dataclass
class Tool:
    """A named question about the BIOS screen.

    `route` is how to get to the screen holding the answer; `reader` is
    what to do once there. Adding a tool means writing one of these, not
    another navigate/read loop.

    `router`, when set, replaces BOTH `route` and `reader`: instead of a
    path decided at import time, it is a function `(tool, session, args,
    mode) -> ToolResult` called with whatever arguments the caller (an
    LLM tool call, or the CLI) supplied for THIS run. This exists because
    every route-based tool answers one question fixed in advance ("what is
    the CPU temperature") -- it cannot answer "go to the screen named X"
    for an X chosen at call time without one Tool per possible X. A router
    resolves its path at call time instead, reusing the same
    `navigate.enter_main_menu_screen` every `hint="nav_menu"` Step already
    goes through -- see `tools/goto_screen.py`.

    `params` describes those caller-supplied arguments as JSON-schema
    properties, so `assistant._tool_schemas()` can hand them to the model.
    Empty for every route-based tool: today none of them take a parameter
    (see assistant.py's docstring), so there is nothing to describe.

    `required_params` names the subset of `params` the tool cannot run
    without; left empty it means "all of them", which is what every tool
    up to `goto_screen` meant. `find_setting` is the first with a genuinely
    optional parameter (`question`), and marking it required would make a
    model invent a question string to satisfy the schema -- inventing
    input to a read-only guard is the last thing wanted here.
    """
    name: str
    question: str
    reader: object
    route: list = field(default_factory=list)
    restore: bool = True
    router: object = None
    params: dict = field(default_factory=dict)
    required_params: list = field(default_factory=list)

    def __post_init__(self):
        keys = []
        for step in self.route:
            keys.append(step.key)
            if step.activate:
                keys.append("enter")
            if step.focus_key:
                keys.append(step.focus_key)
        focus = getattr(self.reader, "focus_key", None)
        if focus:
            keys.append(focus)
        for key in keys:
            if key not in SAFE_KEYS:
                raise UnsafeRoute(
                    f"tool {self.name!r} routes through key {key!r}, which is "
                    f"not in SAFE_KEYS -- read-only tools must not be able to "
                    f"change BIOS settings"
                )

    def run(self, session, mode="keyboard", args=None):
        """Navigate to the screen, then read it. Never raises for a
        navigation or reading miss -- those are answers ("could not
        determine"), reported in the result. Hardware faults
        (`CableNotResponding`, `CameraUnavailable`) do propagate: they mean
        the setup is broken, not that the BIOS said something unexpected.

        `mode` is the operator's choice of how the sidebar legs of the
        route are driven -- "keyboard", "mouse", or "auto" -- passed
        straight through to `enter_main_menu_screen` (see its docstring
        for what each does). It has no effect on a route with no
        `nav_menu` leg.

        `args` is whatever the caller supplied for this run (an LLM tool
        call's arguments, or the CLI's own flags) -- meaningless for a
        route-based tool, which decided everything at import time, so it
        is used only when `router` is set.

        With `restore`, every submenu the tool opened is closed again
        before returning. Without it a tool is single-use: after
        `cpu_temperature` succeeded once, the BIOS was left *inside*
        Hardware Monitor, where that entry no longer exists in the list,
        so the next run could not find it and failed. Closing what we
        opened makes the tool repeatable and leaves the machine roughly
        as it was found -- which also matters for running two tools in a
        row off one session.
        """
        if self.router is not None:
            # A router owns its own screen state -- see `goto_screen`,
            # which sets restore=False on purpose because arriving and
            # STAYING is the entire point of that tool. No `_close_opened`
            # bookkeeping applies here; a router that wants restoring
            # behaviour is responsible for its own cleanup.
            return self.router(self, session, args or {}, mode)

        steps = 0
        opened = 0
        reading = None

        # Answer without moving anything when the answer is already on
        # screen. This is not only faster -- it is what makes the tool
        # robust to where the BIOS happens to be. Running cpu_temperature
        # twice used to fail the second time because the first run left
        # the BIOS inside Hardware Monitor, the very page holding the
        # answer; now that page is simply read.
        if getattr(self.reader, "identifies_screen", False):
            reading = session.read_stable()
            already = self.reader.read(self, session, reading, 0)
            if already.ok:
                return already

        try:
            for leg in self.route:
                # A sidebar leg (hint="nav_menu") always goes through the
                # one shared building block for reaching a top-level
                # screen, instead of each tool re-declaring the same
                # focus_key="left" recipe by hand -- that repetition is
                # exactly how cpu_temperature's route first shipped
                # without it. It also carries the colour-ambiguity
                # fallback (see enter_main_menu_screen's docstring), so a
                # fix there reaches every tool that navigates the sidebar,
                # not just whichever one triggered it.
                if leg.hint == "nav_menu":
                    outcome, _ = enter_main_menu_screen(
                        session, leg.to,
                        activate_key="enter" if leg.activate else None,
                        max_steps=leg.max_steps,
                        mode=mode,
                    )
                    steps += outcome.steps
                    if not outcome.ok:
                        return ToolResult(
                            tool=self.name, ok=False, steps=steps,
                            error=f"nao cheguei em {leg.to!r}: {outcome.reason}"
                                  + (f" ({outcome.detail})" if outcome.detail else ""),
                        )
                    if leg.activate:
                        opened += 1
                    # Discarded on purpose, not captured into `reading`:
                    # what `enter_main_menu_screen` hands back is the cheap
                    # legacy cursor-shaped dict it already needed for its
                    # own arrival check, not a perception contract, and it
                    # would be silently wrong to hand to a `Reader`
                    # expecting `.full`. Measured 2026-08-24: fetching a
                    # real contract here too (`session.read_stable()`) cost
                    # an extra ~1.4-1.8s -- pure waste on every leg but the
                    # last, since the next leg (nav_menu or not) always
                    # overwrites `reading` before anything reads it. Left
                    # as None; the fallback below pays for the one real
                    # contract read exactly once, only if this ends up
                    # being the last leg in the route.
                    reading = None
                    continue

                outcome = move_to(session, leg.spellings, hint=leg.hint,
                                  key=leg.key, max_steps=leg.max_steps,
                                  focus_key=leg.focus_key)
                steps += outcome.steps
                if not outcome.ok:
                    return ToolResult(
                        tool=self.name, ok=False, steps=steps,
                        error=f"nao cheguei em {leg.to!r}: {outcome.reason}"
                              + (f" ({outcome.detail})" if outcome.detail else ""),
                    )
                # Navigation reads through the legacy cursor path, which
                # does not produce a contract -- so a leg that does not
                # open a new screen still needs one perception pass before
                # the reader can work on it.
                if leg.activate:
                    reading = activate(session, "enter")
                    opened += 1
                else:
                    reading = session.read_stable()

            # A tool with no route, or one whose reader cannot recognise
            # its own screen, has not read anything yet.
            if reading is None:
                reading = session.read_stable()
            return self.reader.read(self, session, reading, steps)
        finally:
            # One ESC per ENTER, including on the failure paths above --
            # a tool that gave up halfway must not leave the machine a
            # level deeper than it found it.
            if self.restore:
                _close_opened(session, opened)


_REGISTRY = {}


def register(tool):
    _REGISTRY[tool.name] = tool
    return tool


def get(name):
    key = name.replace("-", "_")
    if key not in _REGISTRY:
        raise UnknownTool(
            f"unknown tool {name!r}. Available: {', '.join(sorted(_REGISTRY))}"
        )
    return _REGISTRY[key]


def all_tools():
    return dict(_REGISTRY)
