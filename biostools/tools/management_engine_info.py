"""Tool: qual a versao do Intel Management Engine (ME) desta maquina?

Mesma rota de `bios_info.py` -- entrar em "Main". Ver a nota em
`ec_info.py` sobre a origem do campo (indice de 2026-08-28) e a ausencia
de fixture de imagem para conferencia offline.

`scroll=True`: 'ME FW Version' esta em screen_index 5 da Main, junto de
`total_memory`/`memory_frequency` -- ver `memory_info.py`.
"""
from ..registry import Field, Fields, Step, Tool, register

MANAGEMENT_ENGINE_INFO = register(Tool(
    name="management_engine_info",
    question="Qual a versao do Intel Management Engine (ME) desta maquina?",
    route=[
        Step(to="main", hint="nav_menu", key="down"),
    ],
    reader=Fields([Field("me_fw_version")], scroll=True),
))
