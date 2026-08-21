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

from . import labels, screen
from .navigate import activate, move_to, walk_group

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
    """
    to: str
    hint: str | None = None
    key: str = "down"
    activate: bool = True
    max_steps: int = 20

    def __post_init__(self):
        self.spellings = labels.screen(self.to)


@dataclass
class ToolResult:
    """One answer.

    `kind` says which payload carries it -- `value` for a single field,
    `values` for a set of them, `entries` for a list of menu options. All
    three keys are always present in the JSON so a consumer can rely on
    the shape without branching first.
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
    """Reader: pull specific labelled fields off the screen we landed on."""
    specs: list

    # Named labels identify their own screen: 'CPU Temperature' exists on
    # the Hardware Monitor page and nowhere else, so finding it is proof
    # of being on the right page. That lets `Tool.run` skip navigating
    # when the answer is already in front of it.
    identifies_screen = True

    def read(self, tool, session, reading, steps):
        full = reading.full
        common = {
            "tool": tool.name, "steps": steps,
            "screen_id": screen.screen_id(full),
            "abstentions": screen.selection_abstentions(full),
        }
        values, notes = {}, []
        single = None

        for spec in self.specs:
            found = screen.field_value(full, spec.spellings, pattern=spec.pattern)
            if found is None:
                notes.append(f"rotulo {spec.label!r} nao esta nesta tela "
                             f"(grafias tentadas: {spec.spellings})")
                continue
            if not found.value:
                notes.append(f"achei {found.label!r} mas nada a direita dele")
                continue
            # `parsed` is None when the pattern did not match: keep the raw
            # text as the answer rather than dropping it. A BIOS value that
            # does not fit the expected shape is exactly the anomaly this
            # system exists to surface.
            values[found.label] = found.parsed or found.value
            single = found

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
    """
    exclude_nav: bool = True

    # Any settings page has label->value pairs, so reading some proves
    # nothing about *which* page this is. Never skip navigation for this.
    identifies_screen = False

    def read(self, tool, session, reading, steps):
        full = reading.full
        exclude = screen.nav_element_ids(full) if self.exclude_nav else frozenset()
        values = screen.field_pairs(full, exclude_ids=exclude)
        return ToolResult(
            tool=tool.name, ok=bool(values), kind="fields", values=values,
            steps=steps, screen_id=screen.screen_id(full),
            abstentions=screen.selection_abstentions(full),
            error=None if values else "nenhum par rotulo/valor nesta tela",
        )


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


@dataclass
class Tool:
    """A named question about the BIOS screen.

    `route` is how to get to the screen holding the answer; `reader` is
    what to do once there. Adding a tool means writing one of these, not
    another navigate/read loop.
    """
    name: str
    question: str
    reader: object
    route: list = field(default_factory=list)
    restore: bool = True

    def __post_init__(self):
        keys = []
        for step in self.route:
            keys.append(step.key)
            if step.activate:
                keys.append("enter")
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

    def run(self, session):
        """Navigate to the screen, then read it. Never raises for a
        navigation or reading miss -- those are answers ("could not
        determine"), reported in the result. Hardware faults
        (`CableNotResponding`, `CameraUnavailable`) do propagate: they mean
        the setup is broken, not that the BIOS said something unexpected.

        With `restore`, every submenu the tool opened is closed again
        before returning. Without it a tool is single-use: after
        `cpu_temperature` succeeded once, the BIOS was left *inside*
        Hardware Monitor, where that entry no longer exists in the list,
        so the next run could not find it and failed. Closing what we
        opened makes the tool repeatable and leaves the machine roughly
        as it was found -- which also matters for running two tools in a
        row off one session.
        """
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
                outcome = move_to(session, leg.spellings, hint=leg.hint,
                                  key=leg.key, max_steps=leg.max_steps)
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
                for _ in range(opened):
                    session.press("esc")


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
