"""Tool: boot por dispositivo removivel, checagem S.M.A.R.T. e reflash do ME estao habilitados?

Mesma tela de `wake_settings.py` ("Advanced", campos proprios, nao um
submenu). Tres toggles de integridade/seguranca de disco e firmware que
convivem no mesmo screenful. `scroll=True`: 'Removable Boot Devices' e
'ME FW Image Re-Flash' estao em screen_index 2, 'S.M.A.R.T. Status
Check' em screen_index 3.
"""
from ..registry import Field, Fields, Step, Tool, register

BOOT_DEVICE_INTEGRITY = register(Tool(
    name="boot_device_integrity",
    question="O boot por dispositivo removivel, a checagem S.M.A.R.T. e o reflash de imagem do ME estao habilitados?",
    route=[
        Step(to="advanced", hint="nav_menu", key="down"),
    ],
    reader=Fields([
        Field("removable_boot_devices"),
        Field("smart_status_check"),
        Field("me_fw_reflash"),
    ], scroll=True),
))
