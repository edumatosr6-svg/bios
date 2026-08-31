"""Tool: como a BIOS esta configurada para pedir senha?

Entra em "Security" (mesmo mecanismo de bios_info, so que apontando para
outra tela de topo -- `enter_main_menu_screen` e agnostico a qual das
seis). `password_check_mode` responde SE a senha e pedida so no Setup ou
tambem no boot (`Password Check: Setup` vs `Always`); e um valor
independente de se uma senha esta de fato definida -- essa segunda
pergunta ("tem senha de administrador?") NAO esta coberta aqui porque a
BIOS escreve o status junto do nome do campo numa unica linha
("Administrator Password -Not Installed"), sem separar rotulo de valor
do jeito que field_value espera -- declarar isso exigiria confirmar como
o motor de percepcao realmente particiona essa linha, o que nao foi
verificado ainda. Ver software-specs.md sobre nao adivinhar particionamento
de texto.

Vem do indice de 2026-08-28 (data/label_index.json) -- primeira tool a
navegar ate Security, entao tambem a primeira sem cobertura offline por
falta de fixture (`captures/` so tem Main/Advanced/Save & Exit
fotografados) -- ver a nota em `ec_info.py`.
"""
from ..registry import Field, Fields, Step, Tool, register

PASSWORD_POLICY = register(Tool(
    name="password_policy",
    question="A BIOS pede senha so para entrar no Setup ou tambem para dar boot?",
    route=[
        Step(to="security", hint="nav_menu", key="down"),
    ],
    reader=Fields([
        Field("password_check_mode"),
        Field("config_inventory_monitoring"),
    ]),
))
