"""Tool: em que modo o controlador SATA esta operando (AHCI, etc.)?

Mesma tela de `wake_settings.py` ("Advanced", campo proprio, nao um
submenu). `scroll=True`: 'SATA Mode Selection' esta em screen_index 1.
"""
from ..registry import Field, Fields, Step, Tool, register

SATA_MODE = register(Tool(
    name="sata_mode",
    question="Em que modo o controlador SATA esta configurado (AHCI, etc.)?",
    route=[
        Step(to="advanced", hint="nav_menu", key="down"),
    ],
    reader=Fields([Field("sata_mode_selection")], scroll=True),
))
