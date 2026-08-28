"""Tool 5: vai ate uma tela do menu principal, escolhida em tempo de chamada.

Todo tool ate aqui declara sua rota fixa (`route=[Step(to="advanced", ...)]`)
-- um caminho decidido quando o modulo e importado. Isso serve bem uma
pergunta sempre igual ("qual a temperatura da CPU"). Nao serve "va ate a
tela de Boot": quem escolhe a tela e o pedido que chega (o usuario, ou o
modelo respondendo por ele), nao o codigo -- e escrever um Tool por tela
do menu principal so para cobrir isso duplicaria seis vezes o mesmo
`route=[Step(to=X, hint="nav_menu")]` sem ganhar nada.

Este tool nao tem `route`: ele tem um `router`, chamado com o argumento
que o pedido trouxe (`{"screen": "boot"}`), que resolve o caminho NA HORA
reaproveitando o mesmissimo `navigate.enter_main_menu_screen` que toda
rota com `hint="nav_menu"` ja usa -- o mesmo ancoramento na seta "Setup",
a mesma verificacao de chegada, o mesmo fallback de clique. Nao e um
caminho novo, e o caminho de sempre, so escolhido tarde -- por isso a IA
consegue "ir ate a tela de Boot" mesmo sem nenhum tool escrito
especificamente para Boot: qualquer nome cadastrado em `labels.SCREENS` ja
e alcancavel por aqui.

`restore=False`, ao contrario de todo tool de leitura: o pedido e chegar e
FICAR na tela. Devolver ao ponto de partida (o que `_close_opened` faz
para os outros) derrotaria o proposito.
"""
from ..navigate import TOP_LEVEL_SCREENS, enter_main_menu_screen
from ..registry import AllFields, Tool, ToolResult, register


def _goto_screen(tool, session, args, mode):
    known = sorted(TOP_LEVEL_SCREENS)
    screen_name = (args or {}).get("screen")
    if not screen_name:
        return ToolResult(
            tool=tool.name, ok=False,
            error=f"faltou o parametro 'screen' (uma de: {', '.join(known)})",
        )

    # Tolerant of how the model spells the argument back ("Boot",
    # "boot ", "save and exit") without inventing a match for a name that
    # is not actually one of the known screens -- see labels.py's own
    # "declared, never guessed" rule, which this respects rather than
    # working around with a fuzzy match on the PARAMETER (fuzzy matching
    # already happens, deliberately, against the SCREEN TEXT inside
    # enter_main_menu_screen).
    normalised = screen_name.strip().lower().replace(" ", "_").replace("-", "_")
    if normalised not in TOP_LEVEL_SCREENS:
        return ToolResult(
            tool=tool.name, ok=False,
            error=f"tela {screen_name!r} desconhecida -- conhecidas: {', '.join(known)}",
        )

    outcome, _ = enter_main_menu_screen(session, normalised, mode=mode)
    if not outcome.ok:
        return ToolResult(
            tool=tool.name, ok=False, steps=outcome.steps,
            error=f"nao cheguei em {normalised!r}: {outcome.reason}"
                  + (f" ({outcome.detail})" if outcome.detail else ""),
        )

    # Read whatever the destination screen shows, the same way `main_info`
    # does for Main -- no fixed label list, because which fields a given
    # screen has is exactly what a caller reaching it by name is likely to
    # not know yet. scroll=True because `goto_screen` can land on ANY
    # top-level screen, and unlike a route hand-written for one specific
    # page, it has no way to know in advance whether everything fits in
    # one frame -- confirmed live 2026-08-28: 'Boot' has more rows
    # (Boot Option #1/#2/#3, ...) than a single frame shows, and the
    # un-scrolled read silently answered with only the top five.
    reading = session.read_stable()
    result = AllFields(scroll=True).read(tool, session, reading, outcome.steps)
    result.notes = [f"cheguei em {normalised!r}"] + result.notes
    # AllFields reports ok=False when the screen has no label/value pairs
    # (Boot's list of boot-order entries is not one). That is not a
    # navigation failure -- arriving is the thing this tool promises, and
    # it happened -- so it is reported as success regardless of what the
    # reader found, with the reader's own notes and values still attached.
    result.ok = True
    return result


GOTO_SCREEN = register(Tool(
    name="goto_screen",
    question=("Navega ate uma tela do menu principal (main, advanced, "
              "security, boot, save_and_exit, event_log) e le TODOS os "
              "campos e valores mostrados nela. Use esta tool para "
              "qualquer pergunta sobre uma configuracao especifica que "
              "nenhuma outra tool nomeie diretamente -- por exemplo, se "
              "'Fast Boot' ou 'Boot Order' estao habilitados fica na tela "
              "'boot'; senhas e nivel de acesso ficam em 'security'."),
    reader=None,
    router=_goto_screen,
    restore=False,
    params={
        "screen": {
            "type": "string",
            "enum": sorted(TOP_LEVEL_SCREENS),
            "description": ("Nome canonico da tela cujos campos devem ser "
                            "lidos, escolhido pelo ASSUNTO da pergunta -- "
                            "ex.: perguntas sobre Fast Boot ou ordem de "
                            "boot usam 'boot'."),
        },
    },
))
