"""Tool: qual a velocidade da ventoinha da CPU?

Mesma rota de `cpu_temperature.py` -- Advanced -> Hardware Monitor -- porque
`cpu_fan_speed` mora na mesma pagina que `cpu_temperature` (ver
labels.FIELDS: as duas ja sao CONFIRMADO, colhidas na mesma sessao ao vivo
de 2026-08-20). Uma tool a parte em vez de estender `cpu_temperature` para
ler os dois: a pergunta "qual a temperatura" e "qual a rotacao do
cooler" sao perguntas diferentes, e `Fields` com mais de um spec muda o
formato da resposta (`kind="fields"` em vez de `kind="field"`, ver
registry.Fields.read) -- misturar as duas obrigaria quem so perguntou uma
a lidar com a resposta da outra tambem.
"""
from ..registry import Field, Fields, Step, Tool, register

# Um numero e "RPM", com o espaco opcional que a formatacao as vezes some.
FAN_SPEED = r"\d+\s*RPM"

CPU_FAN_SPEED = register(Tool(
    name="fan_speed",
    question="Qual a velocidade da ventoinha da CPU?",
    route=[
        # Mesmo raciocinio de cpu_temperature.py: a pagina onde a BIOS esta
        # quando a pergunta chega nao pode ser assumida, entao a perna 1
        # sempre ancora pela barra lateral (hint="nav_menu") em vez de
        # supor que "Advanced" ja esta aberta.
        Step(to="advanced", hint="nav_menu", key="down"),
        Step(to="hardware_monitor", hint="settings_list", key="down"),
    ],
    reader=Fields([Field("cpu_fan_speed", FAN_SPEED)]),
))
