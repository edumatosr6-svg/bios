"""Tool: o Fast Boot esta habilitado?

Entra em "Boot". 'Fast Boot' e o exemplo repetido em varios docstrings do
projeto (find_setting.py, assistant.py) como a pergunta tipica que so
find_setting/goto_screen cobriam ate agora -- esta tool a nomeia
diretamente, respondendo mais rapido (uma leitura, sem passar pelo
indice nem pela busca de conceito).

Vem do indice de 2026-08-28 (data/label_index.json). Ver a nota em
`ec_info.py` sobre a ausencia de fixture de imagem para Boot.
"""
from ..registry import Field, Fields, Step, Tool, register

FAST_BOOT_STATUS = register(Tool(
    name="fast_boot_status",
    question="O Fast Boot esta habilitado?",
    route=[
        Step(to="boot", hint="nav_menu", key="down"),
    ],
    reader=Fields([Field("fast_boot")]),
))
