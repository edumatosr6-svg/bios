"""Tool: qual o display primario e a memoria de video alocada (GTT/Aperture/DVMT)?

Mesma tela de `wake_settings.py` ("Advanced", campos proprios, nao um
submenu). `scroll=True`: 'Primary Display' esta em screen_index 1,
'GTT Size'/'Aperture Size'/'DVMT Pre-Allocated' em screen_index 2 --
o rastreamento por spec de `registry.Fields` cobre os dois.
"""
from ..registry import Field, Fields, Step, Tool, register

GRAPHICS_SETTINGS = register(Tool(
    name="graphics_settings",
    question="Qual o display primario configurado, e quanta memoria de video esta alocada (GTT/Aperture/DVMT)?",
    route=[
        Step(to="advanced", hint="nav_menu", key="down"),
    ],
    reader=Fields([
        Field("primary_display"),
        Field("gtt_size"),
        Field("aperture_size"),
        Field("dvmt_preallocated"),
    ], scroll=True),
))
