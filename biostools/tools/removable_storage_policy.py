"""Tool: qual a politica de acesso a dispositivos de armazenamento removivel?

Mesma tela de `password_policy.py` ("Security"). Ver a nota em
`ec_info.py` sobre a origem (indice de 2026-08-28) e a ausencia de
fixture de imagem.

`scroll=True`: 'Removable Storage Devices Policy' esta em screen_index 1
da Security (Password Check/Config. Inventory Monitoring, que
`password_policy.py` le, ficam no screen_index 0 -- por isso aquela tool
nao precisa rolar e esta nao pode deixar de rolar).
"""
from ..registry import Field, Fields, Step, Tool, register

REMOVABLE_STORAGE_POLICY = register(Tool(
    name="removable_storage_policy",
    question="Qual a politica configurada para dispositivos de armazenamento removivel (USB)?",
    route=[
        Step(to="security", hint="nav_menu", key="down"),
    ],
    reader=Fields([Field("removable_storage_policy")], scroll=True),
))
