"""Tool: as teclas de atalho de boot (F11 popup, PXE apos Wake on LAN) estao ativas?

Mesma tela de `fast_boot_status.py` ("Boot"). Ver a nota em `ec_info.py`
sobre a origem (indice de 2026-08-28) e a ausencia de fixture de imagem.

`scroll=True`: os dois campos NAO estao no mesmo screenful --
'POPUP Boot Menu Hotkey [F11]' e screen_index 0 (mesmo frame de
fast_boot_status), 'PXE Boot after Wake on LAN' e screen_index 1. O
rastreamento por spec de `registry.Fields` cobre os dois independente da
posicao de cada um.
"""
from ..registry import Field, Fields, Step, Tool, register

BOOT_HOTKEYS = register(Tool(
    name="boot_hotkeys",
    question="O atalho de menu de boot (F11) e o PXE boot apos Wake on LAN estao habilitados?",
    route=[
        Step(to="boot", hint="nav_menu", key="down"),
    ],
    reader=Fields([
        Field("popup_boot_hotkey"),
        Field("pxe_boot_after_wol"),
    ], scroll=True),
))
