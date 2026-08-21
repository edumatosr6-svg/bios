"""Tool 3: qual a temperatura da CPU?

A rota reproduz o que foi percorrido a mao contra a maquina real em
2026-08-20: a partir da lista de itens da pagina Advanced, levar o cursor
ate "Hardware Monitor", abrir, e ler o valor ao lado de "CPU Temperature".

So a declaracao mora aqui. Navegacao, verificacao e leitura sao
`registry.Tool.run` -- a proxima tool e outro arquivo desta forma, nao
outro loop.
"""
from ..registry import Field, Fields, Step, Tool, register

# Um numero, um grau opcional, e C ou F. A letra da unidade as vezes se
# perde no OCR; nesse caso o texto cru vira a resposta em vez de falhar --
# uma leitura fora do formato ainda e uma leitura.
TEMPERATURE = r"-?\d+(?:\.\d+)?\s*(?:°|deg)?\s*[cf]\b"

CPU_TEMPERATURE = register(Tool(
    name="cpu_temperature",
    question="Qual a temperatura da CPU?",
    route=[
        Step(to="Hardware Monitor", hint="settings_list", key="down"),
    ],
    reader=Fields([Field("CPU Temperature", TEMPERATURE)]),
))
