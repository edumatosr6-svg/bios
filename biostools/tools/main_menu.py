"""Tool 1: quais opcoes o menu principal oferece?

Percorre o menu de navegacao (a coluna lateral da BIOS Positivo: Main,
Advanced, Security, Boot, Save & Exit, Event Log) sem entrar em nenhuma
delas -- so para saber o que existe.

Nao tem rota: o menu de navegacao esta visivel em qualquer tela, entao a
tool le a partir de onde a BIOS ja estiver. Caminhar pelo menu e o que
distingue opcao de decoracao -- ver `Entries` em ../registry.py.

focus_key="left": confirmado ao vivo (2026-08-21, mesma sessao que achou
o bug em cpu_temperature/main_info/bios_info) -- por padrao o foco do
teclado esta no painel de conteudo, nao na barra lateral, e "left" e o
que entrega o foco a ela. Sem isso a caminhada anda dentro do conteudo
(ex.: rolando por especificacoes de CPU) e nunca toca a barra lateral.
"""
from ..registry import Entries, Tool, register

MAIN_MENU = register(Tool(
    name="main_menu",
    question="Quais opcoes existem no menu principal?",
    reader=Entries(hint="nav_menu", walk=True, focus_key="left"),
))
