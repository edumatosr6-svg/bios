"""Tool: o USB Charger (carregamento em modo DC durante S4/S5) esta habilitado?

Mesma tela de `wake_settings.py` ("Advanced", campo proprio, nao um
submenu). `scroll=True`: 'USB Charger' esta em screen_index 1.
"""
from ..registry import Field, Fields, Step, Tool, register

USB_CHARGER_MODE = register(Tool(
    name="usb_charger_mode",
    question="O USB Charger (carregar dispositivos USB com a maquina desligada) esta habilitado?",
    route=[
        Step(to="advanced", hint="nav_menu", key="down"),
    ],
    reader=Fields([Field("usb_charger")], scroll=True),
))
