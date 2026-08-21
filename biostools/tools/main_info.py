"""Tool 2: o que a tela Main informa (versao da BIOS, etc.)?

Entra em "Main" pelo menu de navegacao e le **todos** os pares
rotulo -> valor da pagina, em vez de uma lista fixa de rotulos.

Por que todos e nao so "BIOS Version": nao existe fixture da tela Main
neste repositorio, entao os rotulos exatos deste modelo de BIOS nao sao
conhecidos -- e cada um dos tres modelos que a fabrica precisa atender
pode escrever os seus de forma diferente. Uma lista fixa devolveria
silenciosamente menos quando um rotulo nao casasse; ler tudo devolve o
que estiver la e deixa a diferenca visivel.

`activate=False`: no menu lateral, mover o cursor ate "Main" ja troca a
pagina exibida a direita. Nao ha nada para abrir com ENTER, e apertar
ENTER aqui entraria num item da pagina em vez de ficar nela.
"""
from ..registry import AllFields, Step, Tool, register

MAIN_INFO = register(Tool(
    name="main_info",
    question="Quais informacoes a tela Main mostra (versao da BIOS, etc.)?",
    route=[
        Step(to="main", hint="nav_menu", key="down", activate=False),
    ],
    reader=AllFields(),
))
