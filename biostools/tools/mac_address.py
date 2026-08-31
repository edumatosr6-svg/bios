"""Tool: qual o endereco MAC desta maquina?

Mesma rota de `bios_info.py` -- entrar em "Main". Ver a nota em
`ec_info.py` sobre a origem do campo (indice de 2026-08-28) e a ausencia
de fixture de imagem para conferencia offline.

`scroll=True`: 'MAC Address' esta em screen_index 2 da Main -- dois
"down" alem do primeiro screenful.
"""
from ..registry import Field, Fields, Step, Tool, register

MAC_ADDRESS = register(Tool(
    name="mac_address",
    question="Qual o endereco MAC desta maquina?",
    route=[
        Step(to="main", hint="nav_menu", key="down"),
    ],
    reader=Fields([Field("mac_address")], scroll=True),
))
