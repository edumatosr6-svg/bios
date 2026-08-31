"""Tool: quais eventos acordam a maquina (LAN, PCI/PCIE, teclado/mouse USB, RTC)?

Entra em "Advanced" -- a MESMA tela de `cpu_temperature`/`fan_speed`, so
que lendo os campos que estao na propria pagina Advanced em vez de
entrar no submenu Hardware Monitor. Os quatro campos vem do indice de
2026-08-28 (data/label_index.json).

`scroll=True`: 'Wake on PCI/PCIE' esta em screen_index 0, os outros tres
em screen_index 1 -- o rastreamento por spec de `registry.Fields` cobre
os dois screenfuls numa so tool.

Sem fixture de imagem para o screenful 1 de Advanced (so screenful 0,
usado por Hardware Monitor, tem foto real) -- ver a nota em
`ec_info.py` sobre o mesmo tipo de lacuna.
"""
from ..registry import Field, Fields, Step, Tool, register

WAKE_SETTINGS = register(Tool(
    name="wake_settings",
    question="Quais eventos estao configurados para acordar a maquina (LAN, PCI/PCIE, teclado/mouse USB, RTC)?",
    route=[
        Step(to="advanced", hint="nav_menu", key="down"),
    ],
    reader=Fields([
        Field("wake_on_pci_pcie"),
        Field("wake_on_lan"),
        Field("wake_on_keyboard_mouse_usb"),
        Field("wake_on_rtc_alarm"),
    ], scroll=True),
))
