"""Tool 3: qual a temperatura da CPU?

Rota de duas pernas, nao uma. A primeira versao assumia que a BIOS ja
estava na lista de itens da pagina Advanced -- e quebrou ao vivo
(2026-08-21) quando a maquina estava na pagina Main: a busca por
"Hardware Monitor" girou dentro da lista errada (a de Main) ate
desistir. A pagina onde a BIOS esta quando a pergunta chega nao pode ser
assumida.

A correcao: a primeira perna vai ate "Advanced" pela barra lateral
(hint="nav_menu") -- toda perna com esse hint passa por
navigate.enter_main_menu_screen, o unico lugar que sabe entregar o foco
do teclado a barra lateral (focus_key="left") e tentar o fallback de cor
quando o detector de destaque abstem por ambiguidade. So depois disso a
segunda perna procura "Hardware Monitor" dentro do conteudo de Advanced
(hint="settings_list").

Nenhum texto de tela aparece aqui -- so conceitos. Como cada modelo de
BIOS escreve "advanced", "hardware_monitor" e "cpu_temperature" mora em
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
        Step(to="advanced", hint="nav_menu", key="down", activate=False),
        # focus_key="right": enter_main_menu_screen (leg above) hands
        # keyboard focus to the sidebar and leaves it there -- "down" here
        # would otherwise walk sidebar tabs instead of Advanced's own
        # content list. "right" is the sidebar's own return path
        # (confirmed live 2026-08-21), handing focus back to content
        # before this leg starts walking it.
        Step(to="hardware_monitor", hint="settings_list", key="down",
             focus_key="right"),
    ],
    reader=Fields([Field("cpu_temperature", TEMPERATURE)]),
))
