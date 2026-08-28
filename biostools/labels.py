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

    # -- Submenus de Advanced -------------------------------------------
    #
    # PREVISOES, ainda sem marca CONFIRMADO -- de proposito.
    #
    # Estas sete entradas existem porque `SUBMENUS` (abaixo) precisa de um
    # nome canonico para cada submenu alvo antes que qualquer coisa possa
    # navegar ate ele: sem grafia declarada, `screen()` levanta
    # `UnknownLabel` e F2 nunca sai do lugar. Declarar a previsao quebra
    # essa circularidade sem custo, porque uma previsao nao marcada nao e
    # tratada como conhecimento em lugar nenhum (ver `SUBMENUS`: elas
    # entram como `provenance="palpite"`, e o tour de F3 e a
    # `find_setting` de F4 recusam palpite).
    #
    # Cada lista traz a entrada de menu e formas alternativas de dizer o
    # MESMO conceito -- nao a caixa de ajuda que a BIOS desenha ao lado
    # dela. "Trusted Computing Settings" e "Device Control Information"
    # estavam aqui e foram removidas: sao texto explicativo, e por serem
    # linhas distintas do painel elas empatavam com a entrada de verdade
    # e faziam `find_setting` abster-se de uma pergunta perfeitamente
    # respondivel. Uma grafia so pertence a esta tabela se for outro
    # jeito de ESCREVER o mesmo item.
    #
    # **Promover uma destas a CONFIRMADO e ato humano, nao do codigo.**
    # O procedimento esta em `study_label_index.py --harvest`: ele despeja
    # o texto cru das telas em `data/raw_labels/<tela>.json` sem casar
    # nada; uma pessoa le o dump, confere com o proprio olho qual linha
    # corresponde a qual conceito, e so entao move a grafia para o topo da
    # lista com `# CONFIRMADO -- Positivo, <data>` e troca a provenance em
    # `SUBMENUS`. Automatizar esse passo anularia a disciplina inteira --
    # a marca passaria a significar "o codigo achou parecido", que e
    # exatamente o que ela existe para nao significar.
    "trusted_computing": [
        "Trusted Computing",
        "TPM Configuration",
    ],
    "device_control": [
        "Device Control",
        "Controle de Dispositivos",
    ],
    "network_stack": [
        "Network Stack Configuration",
        "Network Stack",
    ],
    "mapt": [
        "MAC Address Pass Through (MAPT)",
        "MAC Address Pass Through",
        "MAPT",
    ],
    "smart_charging": [
        "Smart Charging",
        "Carregamento Inteligente",
    ],
    "tls_auth": [
        "TLS Auth Configuration",
        "TIS Auth Configuration",   # o OCR desta BIOS troca 'TL' por 'TI'
        "TLS Auth",
    ],
    "pap": [
        "Positivo Asset Protection (PAP)",
        "Positivo Asset Protection",
        "PAP",
    ],
}

# Onde cada submenu mora: submenu canonico -> {parent, provenance}.
#
# Um mapa declarado, e nao uma descoberta em tempo de execucao, pela mesma
# razao que `SCREENS` e declarado: um submenu ausente daqui simplesmente
# nao e navegavel, em vez de ser adivinhado a partir da linha mais
# parecida da tela. Ver `biostools/submenu.py` para o que consome isto.
#
# `provenance` tem semantica exata e diferente por caminho -- a tabela
# esta em software-specs.md (CA-F2.1a) e replicada em
# `submenu.PROVENANCE_CONFIRMADO`:
#
#   CONFIRMADO -> F2 navega | F3 visita | F4 navega | conta para o KPI K6
#   palpite    -> F2 navega com aviso | F3 pula | F4 abstem | nao conta
#
# **Toda entrada nasce `palpite`.** Promover para CONFIRMADO exige ter
# visto a grafia num dump de `data/raw_labels/` e e edicao humana --
# mesma regra da tabela acima. O verificador de K12
# (`submenu.confirmed_without_evidence`) reprova qualquer CONFIRMADO sem
# linha crua correspondente, entao a marca nao pode ser posta no escuro.
SUBMENUS = {
    "hardware_monitor": {"parent": "advanced", "provenance": "palpite"},
    "trusted_computing": {"parent": "advanced", "provenance": "palpite"},
    "device_control": {"parent": "advanced", "provenance": "palpite"},
    "network_stack": {"parent": "advanced", "provenance": "palpite"},
    "mapt": {"parent": "advanced", "provenance": "palpite"},
    "smart_charging": {"parent": "advanced", "provenance": "palpite"},
    "tls_auth": {"parent": "advanced", "provenance": "palpite"},
    "pap": {"parent": "advanced", "provenance": "palpite"},
}


# How a PERSON asks for a concept -- kept strictly apart from FIELDS and
# SCREENS, which are how a SCREEN spells it.
#
# The separation is load-bearing, not tidiness. `test_biostools.py`
# asserts that `match_score(labels.field("cpu_temperature"),
# "Temperatura da CPU") == 0`, and it is right to: FIELDS is matched
# against text read off the machine, so a Portuguese wording in it would
# be a spelling this BIOS can never show -- dead weight at best, and a
# false match against some other model's screen at worst. The operator's
# language belongs to the question side of the system, so it lives in its
# own table, consulted only by `find_setting` when it resolves a term to
# a concept, and never by any reader matching screen text.
#
# Everything here is unmarked: no screen has displayed any of it, and
# none of it ever will.
TERMS = {
    "cpu_temperature": [
        "Temperatura da CPU",
        "Temperatura do processador",
    ],
    "cpu_fan_speed": [
        "Velocidade da ventoinha da CPU",
        "Rotacao do cooler da CPU",
    ],
    "bios_version": [
        "Versao da BIOS",
    ],
    "bios_build_date": [
        "Data de build da BIOS",
    ],
}


def field(canonical):
    """Every known spelling of a field label."""
    return _resolve(FIELDS, canonical, "campo")


def terms(canonical):
    """How an operator might ask for this concept, in their own words.

    Empty list for a concept with no declared wordings -- absence here is
    normal and means only "nobody has written down another way to ask for
    it", never that the concept is unknown.
    """
    return list(TERMS.get(canonical, ()))


def screen(canonical):
    """Every known spelling of a menu entry / page name."""
    return _resolve(SCREENS, canonical, "tela")


def submenu_parent(canonical):
    """The top-level screen a submenu lives under.

    Raises `UnknownLabel` (not a bare KeyError) for a name absent from
    `SUBMENUS`, naming the known ones -- an unmapped submenu must never be
    attempted, and the caller needs a message it can hand to an operator.
    """
    if canonical not in SUBMENUS:
        raise UnknownLabel(
            f"nenhum submenu cadastrado com o nome {canonical!r}. "
            f"Conhecidos: {', '.join(sorted(SUBMENUS))}. "
            f"Adicione em biostools/labels.py (SUBMENUS)."
        )
    return SUBMENUS[canonical]["parent"]


def submenu_provenance(canonical):
    """`"CONFIRMADO"` or `"palpite"` for a mapped submenu."""
    if canonical not in SUBMENUS:
        raise UnknownLabel(
            f"nenhum submenu cadastrado com o nome {canonical!r}. "
            f"Conhecidos: {', '.join(sorted(SUBMENUS))}."
        )
    return SUBMENUS[canonical]["provenance"]


def submenus_of(parent):
    """Canonical submenus declared as living under `parent`, sorted."""
    return sorted(name for name, entry in SUBMENUS.items()
                  if entry["parent"] == parent)


def _resolve(table, canonical, kind):
    if canonical not in table:
        raise UnknownLabel(
            f"nenhuma grafia cadastrada para o {kind} {canonical!r}. "
            f"Conhecidos: {', '.join(sorted(table))}. "
            f"Adicione em biostools/labels.py."
        )
    return list(table[canonical])
