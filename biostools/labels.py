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
    # Os dois estao na tela Main e no indice colhido desta maquina
    # (data/label_index.json, provenance=CONFIRMADO), mas nao tinham
    # conceito declarado -- entao `find_setting` so os alcancava se o
    # operador escrevesse a grafia inglesa exata. Relatado ao vivo
    # 2026-08-28: "que horario esta no sistema" respondeu "esse ajuste nao
    # existe na BIOS desta maquina", com 'System Time : 16:23:35' visivel
    # na mesma tela. Ver TERMS abaixo para a outra metade do conserto.
    "system_time": [
        "System Time",              # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "system_date": [
        "System Date",              # CONFIRMADO -- Positivo, 2026-08-28
    ],

    # Tudo abaixo vem do mesmo indice colhido em 2026-08-28
    # (data/label_index.json, captured_at 2026-08-28T15:25:44,
    # provenance=CONFIRMADO por entrada) -- grafias reais desta maquina,
    # nunca previstas. Nenhuma tem fixture de imagem em captures/ ainda
    # (so main/advanced/save_and_exit tem foto), entao as tools que as
    # usam nao passam pela suite de regressao com contrato real -- ver a
    # nota nos arquivos de tools que as consomem.
    "ec_build_date": [
        "EC Build Date (MM/DD/YYYY)",   # CONFIRMADO -- Positivo, 2026-08-28
        "EC Build Date",
    ],
    "product_name": [
        "Product Name",             # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "manufacturer_name": [
        "Manufacturer Name",        # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "serial_number": [
        "Serial Number",            # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "total_memory": [
        "Total Memory",             # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "memory_frequency": [
        "Memory Frequency",         # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "mac_address": [
        "MAC Address",              # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "me_fw_version": [
        "ME FW Version",            # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "password_check_mode": [
        "Password Check",           # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "config_inventory_monitoring": [
        "Config. Inventory Monitoring",   # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "removable_storage_policy": [
        "Removable Storage Devices Policy",   # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "flash_write_protection": [
        "Flash Write Protection",   # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "bios_version_downgrade": [
        "BIOS Version Downgrade",   # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "bios_post_logo_delay": [
        "BIOS POST Logo Delay",     # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "bootup_numlock_state": [
        "Bootup NumLock State",     # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "numlock_disabled_preboot": [
        "NumLock Disabled During Pre-Boot",   # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "fast_boot": [
        "Fast Boot",                # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "popup_boot_hotkey": [
        "POPUP Boot Menu Hotkey [F11]",   # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "pxe_boot_after_wol": [
        "PXE Boot after Wake on LAN",   # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "boot_option_1": [
        "Boot Option #1",            # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "boot_option_2": [
        "Boot Option #2",            # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "boot_option_3": [
        "Boot Option #3",            # CONFIRMADO -- Positivo, 2026-08-28
    ],

    # A propria tela Advanced -- nao um submenu -- tambem tem campos
    # rotulo->valor diretos, misturados na mesma lista rolavel que as
    # entradas de submenu (Trusted Computing, Device Control, ...). Mesmo
    # indice de 2026-08-28.
    "wake_on_pci_pcie": [
        "Wake on PCI/PCIE",         # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "wake_on_lan": [
        "Wake on LAN",               # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "wake_on_keyboard_mouse_usb": [
        "Wake on Keyboard/Mouse USB",   # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "wake_on_rtc_alarm": [
        "Wake on RTC Alarm",         # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "usb_charger": [
        "USB Charger",               # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "sata_mode_selection": [
        "SATA Mode Selection",       # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "primary_display": [
        "Primary Display",           # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "gtt_size": [
        "GTT Size",                  # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "aperture_size": [
        "Aperture Size",             # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "dvmt_preallocated": [
        "DVMT Pre-Allocated",        # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "intel_vtd": [
        "Intel VT-d",                # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "intel_virtualization_technology": [
        "Intel Virtualization Technology",   # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "removable_boot_devices": [
        "Removable Boot Devices",    # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "smart_status_check": [
        "S.M.A.R.T. Status Check",   # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "me_fw_reflash": [
        "ME FW Image Re-Flash",      # CONFIRMADO -- Positivo, 2026-08-28
    ],
    "audio_dsp": [
        "Audio DSP",                 # CONFIRMADO -- Positivo, 2026-08-28
    ],

    # Dentro dos submenus de Advanced -- navegados AO VIVO nesta sessao
    # (2026-08-31), nao a partir de um indice colhido antes. Diferente do
    # resto deste arquivo: aqui a maquina real foi vista respondendo, tela
    # por tela, e o texto abaixo e o que a percepcao leu literalmente.
    "tpm_support": [
        "TPM Support",               # CONFIRMADO -- Positivo, 2026-08-31 (Trusted Computing)
    ],
    "tpm_state": [
        "TPM State",                 # CONFIRMADO -- Positivo, 2026-08-31 (Trusted Computing)
    ],
    "tpm_owner_status": [
        "TPM Owner Status",          # CONFIRMADO -- Positivo, 2026-08-31 (Trusted Computing)
        "TPM Owner Status:",         # o OCR le com dois pontos colados ao rotulo
    ],
    "tpm_pending_operation": [
        "Pending operation",         # CONFIRMADO -- Positivo, 2026-08-31 (Trusted Computing)
    ],
    "onboard_video": [
        "Onboard Video",             # CONFIRMADO -- Positivo, 2026-08-31 (Device Control)
    ],
    "hd_audio": [
        "HD Audio",                  # CONFIRMADO -- Positivo, 2026-08-31 (Device Control)
    ],
    "sata_controllers": [
        "SATA Controller(s)",        # CONFIRMADO -- Positivo, 2026-08-31 (Device Control)
    ],
    # 'SIot' (I maiusculo) e como o OCR desta BIOS le 'Slot' aqui --
    # mesmo tipo de troca que TIS/TLS em labels.SCREENS["tls_auth"].
    # Grafia declarada como lida, nao corrigida.
    "m2_slot1_sata_ssd": [
        "M.2 SIot 1 SATA SSD",       # CONFIRMADO -- Positivo, 2026-08-31 (Device Control)
        "M.2 Slot 1 SATA SSD",
    ],
    "m2_slot1_nvme_ssd": [
        "M.2 SIot 1 NVME SSD",       # CONFIRMADO -- Positivo, 2026-08-31 (Device Control)
        "M.2 Slot 1 NVME SSD",
    ],
    "m2_slot2_nvme_ssd": [
        "M.2 SIot 2 NVME SSD",       # CONFIRMADO -- Positivo, 2026-08-31 (Device Control)
        "M.2 Slot 2 NVME SSD",
    ],
    "card_reader": [
        "Card Reader",               # CONFIRMADO -- Positivo, 2026-08-31 (Device Control)
    ],
    "absolute_persistence_version": [
        "Absolute Persistence Version",   # CONFIRMADO -- Positivo, 2026-08-31 (Absolute Persistence)
    ],
    "absolute_persistence_interface_status": [
        "Activation Interface Status",   # CONFIRMADO -- Positivo, 2026-08-31 (Absolute Persistence)
    ],
    "absolute_persistence_activation": [
        "Absolute Persistence",      # CONFIRMADO -- Positivo, 2026-08-31 (Absolute Persistence)
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
    # Visto AO VIVO em 2026-08-31 (nao previsto antes) -- a entrada real
    # da lista de Advanced desta maquina, grafia exata lida pela
    # percepcao. Continua "palpite" mesmo assim: ver a nota logo abaixo
    # sobre promocao ser ato humano, nao do codigo.
    "absolute_persistence": [
        "Absolute Persistence(R) Module",
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
    "absolute_persistence": {"parent": "advanced", "provenance": "palpite"},
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
    # "que horario esta no sistema" chegava aqui e nao casava com nada,
    # entao `concept_spellings` devolvia so o termo cru em portugues, que
    # nao existe em tela nenhuma -- e a resposta honesta "nao existe nesta
    # BIOS" saia para um ajuste que estava visivel na Main. As formas
    # abaixo sao as que uma pessoa realmente usa; a metade em ingles mora
    # em FIELDS, e e ela que o indice contem.
    "system_time": [
        "Hora do sistema",
        "Horario do sistema",
        "Que horas sao",
    ],
    "system_date": [
        "Data do sistema",
        "Que dia e hoje",
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
