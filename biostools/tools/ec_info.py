"""Tool: qual a versao e a data de build do EC (Embedded Controller)?

Mesma rota de `bios_info.py` -- entrar em "Main". `ec_version` ja era
CONFIRMADO desde 2026-08-20 (ver labels.py) mas nenhuma tool nomeada o
lia ainda; `ec_build_date` e novo, colhido no mesmo indice de
2026-08-28 que deu origem a `system_datetime`.

**scroll=True porque os dois campos NAO estao no mesmo screenful.**
Medido em `data/label_index.json`: `EC FW Version` esta em screen_index 0
da tela Main, `EC Build Date (MM/DD/YYYY)` em screen_index 1 -- sem
rolar, a tool encontraria so o primeiro e reportaria o segundo como
"nao esta nesta tela" para sempre, em hardware real tambem, nao so
numa fixture desatualizada. Ver `registry.Fields` sobre o mecanismo.

**Sem fixture de imagem para o screenful 1.** `captures/positivo_main_live.png`
so cobre o screen_index 0 da Main (usado por bios_info/system_datetime);
a rolagem ate `EC Build Date` nao foi conferida contra uma imagem real
desta maquina. Validar ao vivo antes de confiar cegamente.
"""
from ..registry import Field, Fields, Step, Tool, register

EC_INFO = register(Tool(
    name="ec_info",
    question="Qual a versao e a data de build do EC (Embedded Controller)?",
    route=[
        Step(to="main", hint="nav_menu", key="down"),
    ],
    reader=Fields([
        Field("ec_version"),
        Field("ec_build_date"),
    ], scroll=True),
))
