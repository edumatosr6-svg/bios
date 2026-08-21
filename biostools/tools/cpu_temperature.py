"""Tool 3: qual a temperatura da CPU?

A rota reproduz o que foi percorrido a mao contra a maquina real em
2026-08-20: a partir da lista de itens da pagina Advanced, levar o cursor
ate a tela de monitoramento, abrir, e ler o valor ao lado do rotulo de
temperatura da CPU.

Nenhum texto de tela aparece aqui -- so conceitos. Como cada modelo de
BIOS escreve "hardware_monitor" e "cpu_temperature" mora em
../labels.py, que e o unico arquivo a mudar quando um quarto modelo
entrar.
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
        Step(to="hardware_monitor", hint="settings_list", key="down"),
    ],
    reader=Fields([Field("cpu_temperature", TEMPERATURE)]),
))
