"""Canonical labels: what a tool means, separated from what a screen says.

A tool declares a **concept** -- `cpu_temperature` -- and never a piece of
screen text. This module is the one place that knows how each concept is
actually spelled, and it is the only file that changes when a fourth BIOS
model arrives.

Why the split. `Field("CPU Temperature", ...)` conflated two things that
vary independently: what the tool is asking for (fixed forever, in no
language) and how this particular BIOS happens to word it (varies by
manufacturer, by firmware version, and by translation). Conflated, adding
a BIOS model meant editing every tool; separated, it means editing one
dictionary that a person can review in isolation.

**The spellings are declared, never guessed.** Matching still goes through
`screen.match_score`, whose normalisation absorbs how a screen is *drawn*
(the submenu chevron, double spaces, OCR punctuation noise) but not how it
is *worded*. If no spelling matches, the tool abstains -- it never falls
back to the closest-looking line. In a factory reading system a wrong
match (the system temperature reported as the CPU's) is a silent error an
operator acts on, while "não achei o rótulo" is loud and harmless.

**This is a closed problem, not an open one.** The factory serves three
known BIOS models, so this is a finite table that grows when a model is
added, not a general text-understanding problem. That is what makes the
declared-spellings discipline affordable.

**Provenance is marked per entry.** Only what has been seen on real
hardware is marked CONFIRMADO; everything else is a prediction that has
never matched anything, and should be treated as a guess until a real
capture proves it. Removing that distinction would let an untested guess
look like knowledge.

Filling the table for a new model is a job for the LLM *offline*: hand it
the raw labels perception already extracted from a handful of that model's
screens, ask which corresponds to each concept, review by eye, paste here.
It never runs in the hot path -- reading stays `match_score` against a
finite list.
"""

class UnknownLabel(KeyError):
    """A tool asked for a concept this module has no spellings for."""


# Text that appears to the LEFT of a value in a settings table.
FIELDS = {
    "cpu_temperature": [
        "CPU Temperature",          # CONFIRMADO -- Positivo, 2026-08-20
        "CPU Temp",
        "Processor Temperature",
        "CPU Package Temperature",
    ],
    "cpu_fan_speed": [
        "CPU Fan Speed",            # CONFIRMADO -- Positivo, 2026-08-20
        "CPU FAN Speed",
        "Processor Fan Speed",
    ],
    "bios_version": [
        "BIOS Version",             # CONFIRMADO -- Positivo, 2026-08-20
        "BIOS Revision",
        "Firmware Version",
    ],
    "bios_build_date": [
        "BIOS Build Date (MM/DD/YYYY)",   # CONFIRMADO -- Positivo, 2026-08-20
        "BIOS Build Date",
        "Build Date",
    ],
    "ec_version": [
        "EC FW Version",            # CONFIRMADO -- Positivo, 2026-08-20
        "EC Version",
    ],
    "platform_type": [
        "Platform BIOS Type",       # CONFIRMADO -- Positivo, 2026-08-20
        "Platform Type",
    ],
}

# Text that is navigated *to* -- a menu entry or a page name.
SCREENS = {
    "main": [
        "Main",                     # CONFIRMADO -- Positivo, 2026-08-20
        "Principal",
    ],
    "advanced": [
        "Advanced",                 # CONFIRMADO -- Positivo, 2026-08-20
        "Avançado",
    ],
    "hardware_monitor": [
        "Hardware Monitor",         # CONFIRMADO -- Positivo, 2026-08-20
        "H/W Monitor",
        "HW Monitor",
        "PC Health Status",         # comum em BIOS AMI
        "Monitor de Hardware",
    ],
    "security": [
        "Security",                 # CONFIRMADO -- Positivo, 2026-08-20
        "Segurança",
    ],
    "boot": [
        "Boot",                     # CONFIRMADO -- Positivo, 2026-08-20
        "Inicialização",
    ],
    "save_and_exit": [
        "Save & Exit",              # CONFIRMADO -- Positivo, 2026-08-20
        "Save and Exit",
        "Exit",
        "Salvar e Sair",
    ],
    "event_log": [
        "Event Log",                # CONFIRMADO -- Positivo, 2026-08-20
        "Registro de Eventos",
    ],
}


def field(canonical):
    """Every known spelling of a field label."""
    return _resolve(FIELDS, canonical, "campo")


def screen(canonical):
    """Every known spelling of a menu entry / page name."""
    return _resolve(SCREENS, canonical, "tela")


def _resolve(table, canonical, kind):
    if canonical not in table:
        raise UnknownLabel(
            f"nenhuma grafia cadastrada para o {kind} {canonical!r}. "
            f"Conhecidos: {', '.join(sorted(table))}. "
            f"Adicione em biostools/labels.py."
        )
    return list(table[canonical])
