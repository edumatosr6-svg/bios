"""Tool: qual a ordem de boot configurada (as tres primeiras prioridades)?

Mesma tela de `fast_boot_status.py` ("Boot"). Le so #1-#3: sao onze
entradas ao todo no indice colhido (`Boot Option #1` .. `#11`), e as
tres primeiras cobrem a pergunta que um operador realmente faz ("qual o
disco de boot primario"); as demais continuam alcancaveis por
`goto_screen(screen="boot")`, que le a tela inteira sem precisar de um
Field nomeado por entrada.

Ver a nota em `ec_info.py` sobre a origem (indice de 2026-08-28) e a
ausencia de fixture de imagem.

`scroll=True`: as tres (Boot Option #1-#3) estao em screen_index 1 da
Boot, um "down" alem do screenful de `fast_boot_status`/`numlock_settings`/
`bios_post_settings`.
"""
from ..registry import Field, Fields, Step, Tool, register

BOOT_ORDER = register(Tool(
    name="boot_order",
    question="Qual a ordem de boot configurada (as tres primeiras prioridades)?",
    route=[
        Step(to="boot", hint="nav_menu", key="down"),
    ],
    reader=Fields([
        Field("boot_option_1"),
        Field("boot_option_2"),
        Field("boot_option_3"),
    ], scroll=True),
))
