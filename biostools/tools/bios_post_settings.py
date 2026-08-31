"""Tool: por quanto tempo o logo de POST fica visivel?

Mesma tela de `fast_boot_status.py` ("Boot"). Ver a nota em `ec_info.py`
sobre a origem (indice de 2026-08-28) e a ausencia de fixture de imagem.
"""
from ..registry import Field, Fields, Step, Tool, register

BIOS_POST_SETTINGS = register(Tool(
    name="bios_post_settings",
    question="Por quanto tempo o logo da BIOS fica visivel durante o POST?",
    route=[
        Step(to="boot", hint="nav_menu", key="down"),
    ],
    reader=Fields([Field("bios_post_logo_delay")]),
))
