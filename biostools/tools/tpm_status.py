"""Tool: o TPM (Trusted Platform Module) esta habilitado, e qual o estado dele?

Mesma forma de rota de `cpu_temperature.py`/`fan_speed.py`: perna 1 entra
em "Advanced" pela barra lateral, perna 2 caminha ate "Trusted Computing"
dentro do conteudo e abre com ENTER. Navegado AO VIVO nesta sessao
(2026-08-31) contra hardware real -- a tela que abre mostra TPM
Support/TPM State/TPM Owner Status/Pending operation, nunca o texto
"Trusted Computing" de volta, o que e exatamente por isso que esta tool
usa `route`/`Step` (que so pede para achar a ENTRADA do menu e abrir) em
vez de `submenu.enter_submenu` (que tambem exige que a tela seguinte
repita o proprio nome -- e essa BIOS especifica nao repete, entao aquele
caminho abstem aqui mesmo tendo chegado no lugar certo).
"""
from ..registry import Field, Fields, Step, Tool, register

TPM_STATUS = register(Tool(
    name="tpm_status",
    question="O TPM (Trusted Platform Module) esta habilitado, e qual o estado/status dele?",
    route=[
        Step(to="advanced", hint="nav_menu", key="down"),
        Step(to="trusted_computing", hint="settings_list", key="down"),
    ],
    reader=Fields([
        Field("tpm_support"),
        Field("tpm_state"),
        Field("tpm_owner_status"),
        Field("tpm_pending_operation"),
    ], scroll=True),
))
