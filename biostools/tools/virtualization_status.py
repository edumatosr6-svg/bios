"""Tool: a virtualizacao (Intel VT-d e VT-x) esta habilitada?

Mesma tela de `wake_settings.py` ("Advanced", campos proprios, nao um
submenu). `scroll=True`: os dois estao em screen_index 2.
"""
from ..registry import Field, Fields, Step, Tool, register

VIRTUALIZATION_STATUS = register(Tool(
    name="virtualization_status",
    question="A virtualizacao (Intel VT-d e Intel Virtualization Technology / VT-x) esta habilitada?",
    route=[
        Step(to="advanced", hint="nav_menu", key="down"),
    ],
    reader=Fields([
        Field("intel_vtd"),
        Field("intel_virtualization_technology"),
    ], scroll=True),
))
