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
        # activate=True (o padrao): sem o ENTER o cursor chega em
        # "Advanced" na barra lateral mas a pagina exibida continua sendo a
        # anterior -- e a perna 2 entao procura "Hardware Monitor" dentro
        # do conteudo da tela errada. Foi exatamente essa a falha relatada
        # ("estou na Main e nao consigo ir para a Advanced"), fotografada
        # em captures/handshake/ e corrigida em 2026-08-24. Ver
        # navigate.enter_main_menu_screen.
        Step(to="advanced", hint="nav_menu", key="down"),
        # Sem focus_key. O "right" que estava aqui vinha de quando a perna
        # 1 nao apertava ENTER e deixava o foco preso na barra lateral.
        # Agora que ela abre a pagina de verdade, o ENTER ja entrega o foco
        # ao conteudo -- medido 2026-08-24: logo apos abrir a Advanced o
        # cursor esta em "MAC Address Pass-Through (MAPT)", o primeiro item
        # da lista. Um "right" aqui tiraria o foco do conteudo e o mandaria
        # para a coluna de icones da direita (Previous Values / Optimized
        # Defaults / Back), e a caminhada nunca acharia nada.
        Step(to="hardware_monitor", hint="settings_list", key="down"),
    ],
    reader=Fields([Field("cpu_temperature", TEMPERATURE)]),
))
