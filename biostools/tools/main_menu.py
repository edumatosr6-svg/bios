"""Tool 1: quais opcoes o menu principal oferece?

Percorre o menu de navegacao (a coluna lateral da BIOS Positivo: Main,
Advanced, Security, Boot, Save & Exit, Event Log) sem entrar em nenhuma
delas -- so para saber o que existe.

Nao tem rota: o menu de navegacao esta visivel em qualquer tela, entao a
tool le a partir de onde a BIOS ja estiver. Caminhar pelo menu e o que
distingue opcao de decoracao -- ver `Entries` em ../registry.py.

`focus_key` esta como None de proposito. Se ao vivo as setas mexerem no
painel de conteudo em vez do menu lateral, e essa a manopla: passar a
tecla que devolve o foco para o menu (tipicamente "left" ou "esc") na
declaracao abaixo. Isso ainda nao foi testado contra hardware.
"""
from ..registry import Entries, Tool, register

MAIN_MENU = register(Tool(
    name="main_menu",
    question="Quais opcoes existem no menu principal?",
    reader=Entries(hint="nav_menu", walk=True, focus_key=None),
))
