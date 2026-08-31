"""Tool: o Audio DSP esta habilitado?

Mesma tela de `wake_settings.py` ("Advanced", campo proprio, nao um
submenu). `scroll=True`: 'Audio DSP' esta em screen_index 3, o mais
distante do topo entre os campos proprios de Advanced ja declarados.
"""
from ..registry import Field, Fields, Step, Tool, register

AUDIO_DSP_STATUS = register(Tool(
    name="audio_dsp_status",
    question="O Audio DSP esta habilitado?",
    route=[
        Step(to="advanced", hint="nav_menu", key="down"),
    ],
    reader=Fields([Field("audio_dsp")], scroll=True),
))
