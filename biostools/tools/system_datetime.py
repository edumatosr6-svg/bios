"""Tool: que dia e hora estao configurados na BIOS?

Mesma rota de `bios_info.py` -- entrar em "Main" -- porque `system_time` e
`system_date` moram na mesma tela que versao/build date/plataforma (ver
labels.FIELDS: os dois ja sao CONFIRMADO, colhidos ao vivo em 2026-08-28,
o mesmo incidente documentado em labels.py: "que horario esta no sistema"
respondeu "nao existe" ate os dois ganharem grafia declarada). Nomear os
dois aqui poupa o find_setting/explore_setting de resolver essa pergunta a
cada vez -- a mesma economia que bios_info ja da para versao/build date.
"""
from ..registry import Field, Fields, Step, Tool, register

SYSTEM_DATETIME = register(Tool(
    name="system_datetime",
    question="Que data e hora estao configuradas na BIOS?",
    route=[
        Step(to="main", hint="nav_menu", key="down"),
    ],
    reader=Fields([
        Field("system_time"),
        Field("system_date"),
    ]),
))
