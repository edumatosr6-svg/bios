"""Tool 4: versao, data de build e tipo de plataforma da BIOS.

Mesma rota do `main_info` (entrar em "Main" move o cursor, nao abre
nada), mas le so os tres campos pedidos em vez da tela inteira -- a
diferenca entre `main_info` (o que existe, sem saber os nomes) e esta
tool (concept conhecido, resposta nomeada). Ambas convivem: uma nao
substitui a outra.

A rota (hint="nav_menu") passa por navigate.enter_main_menu_screen, que
entrega o foco do teclado a barra lateral (focus_key="left" -- ver seu
docstring para a medicao ao vivo que forcou isso, 2026-08-21) e tenta um
fallback de cor quando o detector de destaque abstem por ambiguidade.
"""
from ..registry import Field, Fields, Step, Tool, register

BIOS_INFO = register(Tool(
    name="bios_info",
    question="Qual a versao, data de build e tipo de plataforma da BIOS?",
    route=[
        Step(to="main", hint="nav_menu", key="down", activate=False),
    ],
    reader=Fields([
        Field("bios_version"),
        Field("bios_build_date"),
        Field("platform_type"),
    ]),
))
