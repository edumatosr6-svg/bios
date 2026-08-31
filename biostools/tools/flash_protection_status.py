"""Tool: a protecao de escrita da flash e o downgrade de BIOS estao habilitados?

Mesma tela de `password_policy.py` ("Security"). Os dois campos sao
independentes um do outro mas convivem no mesmo screenful (screen_index
1) -- juntar poupa uma segunda navegacao para quem pergunta os dois. Ver
a nota em `ec_info.py` sobre a origem (indice de 2026-08-28) e a
ausencia de fixture de imagem.

`scroll=True` pelo mesmo motivo de `removable_storage_policy.py`:
screen_index 1, nao 0.
"""
from ..registry import Field, Fields, Step, Tool, register

FLASH_PROTECTION_STATUS = register(Tool(
    name="flash_protection_status",
    question="A protecao de escrita da flash esta ativa, e o downgrade de BIOS esta permitido?",
    route=[
        Step(to="security", hint="nav_menu", key="down"),
    ],
    reader=Fields([
        Field("flash_write_protection"),
        Field("bios_version_downgrade"),
    ], scroll=True),
))
