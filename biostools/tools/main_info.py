"""Tool 2: o que a tela Main informa (versao da BIOS, etc.)?

Entra em "Main" pelo menu de navegacao e le **todos** os pares
rotulo -> valor da pagina, em vez de uma lista fixa de rotulos.

Por que todos e nao so "BIOS Version": nao existe fixture da tela Main
neste repositorio, entao os rotulos exatos deste modelo de BIOS nao sao
conhecidos -- e cada um dos tres modelos que a fabrica precisa atender
pode escrever os seus de forma diferente. Uma lista fixa devolveria
silenciosamente menos quando um rotulo nao casasse; ler tudo devolve o
que estiver la e deixa a diferenca visivel.

A rota (hint="nav_menu") passa por navigate.enter_main_menu_screen, que
ancora o cursor na seta "Setup" do topo da barra lateral, conta ate
"Main" e so entao aperta ENTER -- ver
docs/specs/f-specs/navegacao-ancorada-barra-lateral.md. `activate` fica
no padrao True: mover o cursor ate "Main" NAO troca a pagina exibida
nesta BIOS -- medido ao vivo 2026-08-24, contrariando o que este
docstring afirmava antes (a suposicao nunca tinha sido testada partindo
de outra pagina). Sem o ENTER a tool lia os campos da pagina anterior.
"""
from ..registry import AllFields, Step, Tool, register

MAIN_INFO = register(Tool(
    name="main_info",
    question="Quais informacoes a tela Main mostra (versao da BIOS, etc.)?",
    route=[
        Step(to="main", hint="nav_menu", key="down"),
    ],
    reader=AllFields(),
))
