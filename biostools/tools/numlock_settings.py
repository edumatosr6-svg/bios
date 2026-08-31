"""Tool: qual o estado do NumLock na inicializacao?

Mesma tela de `fast_boot_status.py` ("Boot"). Ver a nota em `ec_info.py`
sobre a origem (indice de 2026-08-28) e a ausencia de fixture de imagem.
"""
from ..registry import Field, Fields, Step, Tool, register

NUMLOCK_SETTINGS = register(Tool(
    name="numlock_settings",
    question="O NumLock inicia ligado ou desligado, e fica desabilitado antes do boot?",
    route=[
        Step(to="boot", hint="nav_menu", key="down"),
    ],
    reader=Fields([
        Field("bootup_numlock_state"),
        Field("numlock_disabled_preboot"),
    ]),
))
