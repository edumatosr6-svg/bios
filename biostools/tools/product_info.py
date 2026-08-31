"""Tool: nome do produto, fabricante e numero de serie desta maquina.

Mesma rota de `bios_info.py` -- entrar em "Main". Os tres campos vem do
mesmo indice de 2026-08-28 (data/label_index.json) que deu origem a
`system_datetime`/`ec_info`.

`scroll=True`: os tres estao em screen_index 1 da Main (um "down" alem
do screen_index 0 onde System Time/EC FW Version ficam) -- sem rolar,
nenhum dos tres seria achado nunca. Ver a nota em `ec_info.py` sobre a
ausencia de fixture de imagem para esse screenful.
"""
from ..registry import Field, Fields, Step, Tool, register

PRODUCT_INFO = register(Tool(
    name="product_info",
    question="Qual o nome do produto, o fabricante e o numero de serie desta maquina?",
    route=[
        Step(to="main", hint="nav_menu", key="down"),
    ],
    reader=Fields([
        Field("product_name"),
        Field("manufacturer_name"),
        Field("serial_number"),
    ], scroll=True),
))
