"""Tool: quanta memoria RAM esta instalada e em que frequencia.

Mesma rota de `bios_info.py` -- entrar em "Main". Ver a nota em
`ec_info.py` sobre a origem dos dois campos (indice de 2026-08-28) e a
ausencia de fixture de imagem para conferencia offline.

`scroll=True`: os dois estao em screen_index 5 da Main -- cinco "down"
alem do primeiro screenful (a tela tem sete ao todo).
"""
from ..registry import Field, Fields, Step, Tool, register

MEMORY_INFO = register(Tool(
    name="memory_info",
    question="Quanta memoria RAM esta instalada e em que frequencia?",
    route=[
        Step(to="main", hint="nav_menu", key="down"),
    ],
    reader=Fields([
        Field("total_memory"),
        Field("memory_frequency"),
    ], scroll=True),
))
