"""Tool 4: versao, data de build e tipo de plataforma da BIOS.

Mesma rota do `main_info` (entrar em "Main"), mas le so os tres campos
pedidos em vez da tela inteira -- a diferenca entre `main_info` (o que
existe, sem saber os nomes) e esta tool (concept conhecido, resposta
nomeada). Ambas convivem: uma nao substitui a outra.

A rota (hint="nav_menu") passa por navigate.enter_main_menu_screen, que
ancora o cursor na seta "Setup" do topo da barra lateral, conta ate
"Main" e so entao aperta ENTER -- ver
docs/specs/f-specs/navegacao-ancorada-barra-lateral.md. `activate` fica
no padrao True: sem ENTER o cursor chega em "Main" na barra mas a pagina
exibida continua sendo a anterior, e os tres campos abaixo seriam lidos
da tela errada -- foi exatamente esse bug que a tool herdou por copiar a
rota original de cpu_temperature (corrigido 2026-08-24).
"""
from ..registry import Field, Fields, Step, Tool, register

BIOS_INFO = register(Tool(
    name="bios_info",
    question="Qual a versao, data de build e tipo de plataforma da BIOS?",
    route=[
        Step(to="main", hint="nav_menu", key="down"),
    ],
    reader=Fields([
        Field("bios_version"),
        Field("bios_build_date"),
        Field("platform_type"),
    ]),
))
