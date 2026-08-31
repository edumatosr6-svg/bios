"""Tool: o Absolute Persistence esta ativo, e qual a versao/status da interface?

Mesma forma de rota de `tpm_status.py`, ate um submenu recem-descoberto
AO VIVO nesta sessao (2026-08-31): "Absolute Persistence(R) Module" nao
estava em labels.py antes de ninguem navegar ate a lista de Advanced
desta maquina e ler a entrada de verdade -- ver a nota em `labels.py`
(SCREENS["absolute_persistence"]).
"""
from ..registry import Field, Fields, Step, Tool, register

ABSOLUTE_PERSISTENCE_STATUS = register(Tool(
    name="absolute_persistence_status",
    question="O Absolute Persistence esta ativo, e qual a versao e o status da interface de ativacao?",
    route=[
        Step(to="advanced", hint="nav_menu", key="down"),
        Step(to="absolute_persistence", hint="settings_list", key="down"),
    ],
    reader=Fields([
        Field("absolute_persistence_version"),
        Field("absolute_persistence_interface_status"),
        Field("absolute_persistence_activation"),
    ], scroll=True),
))
