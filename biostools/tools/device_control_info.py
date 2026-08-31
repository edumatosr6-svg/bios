"""Tool: quais dispositivos onboard estao habilitados (video, audio, SATA, M.2, leitor de cartao)?

Mesma forma de rota de `tpm_status.py`, so que caminhando ate "Device
Control" em vez de "Trusted Computing". Navegado AO VIVO nesta sessao
(2026-08-31) contra hardware real -- ver a nota em `tpm_status.py` sobre
por que `route`/`Step` e usado em vez de `submenu.enter_submenu` para
estes submenus.

'M.2 SIot' (I maiusculo) e como o OCR desta BIOS le 'Slot' -- ver
labels.py.
"""
from ..registry import Field, Fields, Step, Tool, register

DEVICE_CONTROL_INFO = register(Tool(
    name="device_control_info",
    question="Quais dispositivos onboard estao habilitados (video, audio, controladores SATA, SSDs M.2, leitor de cartao)?",
    route=[
        Step(to="advanced", hint="nav_menu", key="down"),
        Step(to="device_control", hint="settings_list", key="down"),
    ],
    reader=Fields([
        Field("onboard_video"),
        Field("hd_audio"),
        Field("sata_controllers"),
        Field("m2_slot1_sata_ssd"),
        Field("m2_slot1_nvme_ssd"),
        Field("m2_slot2_nvme_ssd"),
        Field("card_reader"),
    ], scroll=True),
))
