"""Tool 7: quando `find_setting` nao acha o termo, procura AO VIVO.

`find_setting` responde a partir de `data/label_index.json` -- um indice
colhido uma vez, por uma tour humana (F3). Isso e rapido e verificado,
mas tem um ponto cego especifico: um ajuste que existe de verdade nesta
BIOS e simplesmente nunca foi colhido (ou foi colhido antes de alguem
declarar o conceito em `labels.py`) responde "nao existe nesta maquina" --
uma mentira honesta, no sentido de que o codigo nao inventou nada, mas
ainda assim errada. Foi exatamente isso que aconteceu ao vivo 2026-08-28:
"que horario esta no sistema" respondeu "nao existe", com 'System Time :
16:23:35' visivel na propria tela Main -- o indice tinha a entrada, mas
`system_time` nao era um conceito declarado em `labels.FIELDS`/`TERMS`
ainda, entao a busca nunca alcancava aquela linha do indice.

Esta tool cobre esse ponto cego sem abrir mao da disciplina do projeto
("nunca casa por parecido, so por grafia declarada e verificada"):
percorre as seis telas do menu principal AO VIVO, uma por vez, rolando
cada pagina inteira (`page.scan_page`, o mesmo mecanismo de F1) e
comparando cada rotulo lido contra as grafias que `find_setting.
concept_spellings` ja sabe expandir -- a mesma funcao de casamento, so que
aplicada ao texto lido agora em vez de a um indice congelado. Achou, le o
valor de verdade e devolve; nao achou em lugar nenhum, devolve a mesma
frase honesta de "nao existe" que `find_setting` usa, junto com a lista
do que foi de fato visitado.

**O que esta tool NAO faz, de proposito:**

* nao entra em `save_and_exit` -- fronteira R6, a mesma de todo o resto do
  projeto: nenhum caminho automatico visita a tela cujo unico proposito e
  confirmar ou descartar configuracao;
* nao entra em submenu nao confirmado (`labels.SUBMENUS[...]
  ["provenance"] != "CONFIRMADO"`) -- mesma guarda R5/CA-F2.1a que
  `submenu.enter_submenu` ja aplica para F3/F4. Hoje isso significa
  varrer so as seis paginas de topo, porque nenhum submenu foi promovido
  a CONFIRMADO ainda; o dia em que um humano promover um, esta tool passa
  a alcanca-lo sem precisar ser reescrita;
* nao aceita nenhum verbo de mudanca -- roda o MESMO `write_request` que
  `find_setting` usa, nao uma copia.

Mais lento que `find_setting` de proposito: uma varredura ao vivo custa
uma pagina inteira rolada por tela visitada (ate `page.MAX_SCREENS`
screenful cada), contra uma busca em memoria sobre um indice ja colhido.
Por isso o system prompt so manda tentar isto DEPOIS de `find_setting`
abstinar -- ver `assistant._SYSTEM_PROMPT`.

**Um achado nao e esquecido.** Toda vez que a varredura acerta, a
localizacao (tela, e submenu se houver -- nunca o VALOR) e gravada em
`discovered.py`. Da proxima vez que alguem perguntar o mesmo ajuste (ou
um sinonimo que expanda para o mesmo rotulo), `find_setting` confere esse
cache antes de abstinar, pula direto para aquela unica tela e le de novo
ao vivo -- sem varrer as cinco. So a POSICAO e memorizada; o valor em si
nunca vem do cache, porque um relogio ou um estado liga/desliga muda sem
que a localizacao do campo mude junto.
"""
from __future__ import annotations

from . import find_setting as find_setting_mod
from .. import discovered as discovered_mod
from .. import labels
from .. import submenu as submenu_mod
from ..navigate import TOP_LEVEL_SCREENS, enter_main_menu_screen, looks_like_dialog
from ..page import MAX_SCREENS, NORMALISE_MARGIN, find_pair, scan_page
from ..registry import Tool, ToolResult, register

# save_and_exit e uma tela de topo, mas nunca uma tela a visitar -- R6, a
# mesma fronteira que `submenu.enter_submenu` recusa antes de mandar
# qualquer tecla.
_CRAWL_SCREENS = tuple(s for s in TOP_LEVEL_SCREENS if s != "save_and_exit")


def _close(session, opened):
    """Um ESC por nivel aberto ao checar um submenu que deu em nada.

    Mesma disciplina de `registry._close_opened` e `submenu._restore`,
    repetida aqui em vez de importada de um nome privado de outro modulo
    -- a mesma forma pequena e ja compreendida, contida no modulo que a
    usa. Olha entre cada ESC porque esta BIOS responde um ESC as cegas no
    nivel de topo com um dialogo de confirmacao, nunca com "subir um
    nivel".
    """
    for _ in range(opened):
        session.press("esc")
        if looks_like_dialog(session.read_cursor()):
            session.press("esc")
            return


def _crawl_screen(session, screen_name, targets, mode):
    """Varre uma tela de topo (e seus submenus CONFIRMADOs) por `targets`.

    Retorna `(hit, steps, visited_note, skipped_submenus)`, onde `hit` e
    `(screen, submenu, label, value)` ou None -- `submenu` e None quando o
    achado esta na propria tela de topo. `visited_note` descreve o que foi
    tentado, para a mensagem final.
    """
    steps = 0
    outcome, _ = enter_main_menu_screen(session, screen_name, mode=mode)
    steps += outcome.steps
    if not outcome.ok:
        return None, steps, f"{screen_name} (nao alcancei: {outcome.reason})", []

    scan = scan_page(session, max_screens=MAX_SCREENS)
    steps += (MAX_SCREENS + NORMALISE_MARGIN) + scan.total_screens
    note = screen_name + (" (varredura truncada)" if scan.truncated else "")

    found = find_pair(scan, targets)
    if found is not None:
        index, label, value = found
        return (screen_name, None, label, value), steps, note, []

    skipped = []
    for sub in sorted(labels.SUBMENUS):
        info = labels.SUBMENUS[sub]
        if info["parent"] != screen_name:
            continue
        if not submenu_mod.is_confirmed(sub):
            skipped.append(sub)
            continue

        # restore=False: fica DENTRO do submenu para poder varrer a
        # pagina dele -- restore=True fecharia antes mesmo de eu ler
        # qualquer coisa la dentro. O fechamento e responsabilidade desta
        # funcao (`_close`, abaixo), nao de `enter_submenu`.
        arrival = submenu_mod.enter_submenu(session, sub, mode=mode, restore=False)
        steps += arrival.steps
        if not arrival.ok:
            note += f"; {screen_name}/{sub} (nao alcancei: {arrival.reason})"
            continue

        sub_scan = scan_page(session, max_screens=MAX_SCREENS)
        steps += (MAX_SCREENS + NORMALISE_MARGIN) + sub_scan.total_screens
        note += f"; {screen_name}/{sub}" + (
            " (varredura truncada)" if sub_scan.truncated else "")

        sub_found = find_pair(sub_scan, targets)
        if sub_found is not None:
            index, label, value = sub_found
            # Achou -- fica aqui, mesma convencao de find_setting/
            # goto_screen: a resposta certa e mostrada onde foi lida.
            return (screen_name, sub, label, value), steps, note, skipped

        _close(session, arrival.opened)

    return None, steps, note, skipped


def _explore_setting(tool, session, args, mode):
    args = args or {}
    term = (args.get("term") or "").strip()
    question = (args.get("question") or "").strip() or None

    if not term:
        return ToolResult(
            tool=tool.name, ok=False,
            error="faltou o parâmetro obrigatório 'term' (o nome do ajuste "
                  "procurado, ex.: --term \"Fast Boot\")",
        )

    # Mesma guarda de find_setting, mesma funcao -- nao uma copia.
    verb = find_setting_mod.write_request(term, question)
    if verb:
        return ToolResult(
            tool=tool.name, ok=False, kind="field", value=None,
            error=find_setting_mod.READ_ONLY_REFUSAL,
            notes=[f"verbo de alteração detectado: {verb!r}",
                   "nenhuma tecla foi enviada à máquina"],
        )

    targets = find_setting_mod.concept_spellings(term)
    steps = 0
    visited = []
    skipped_submenus = []

    for screen_name in _CRAWL_SCREENS:
        hit, screen_steps, note, skipped = _crawl_screen(
            session, screen_name, targets, mode)
        steps += screen_steps
        visited.append(note)
        skipped_submenus += skipped

        if hit is not None:
            hit_screen, hit_submenu, label, value = hit
            local = hit_screen + (f"/{hit_submenu}" if hit_submenu else "")
            # Grava ONDE foi achado, nunca o valor -- a proxima leitura
            # deste rotulo (via find_setting) volta a esta localizacao e
            # le de novo AO VIVO. Ver discovered.py: e cache de posicao,
            # nunca de resposta.
            discovered_mod.remember(
                label=label, screen=hit_screen, submenu=hit_submenu, term=term)
            return ToolResult(
                tool=tool.name, ok=True, kind="field", label=label,
                value=value, raw_value=value, steps=steps,
                notes=[f"achado ao vivo em {local} (varredura em tempo real, "
                       f"sem depender do índice) -- localização memorizada "
                       f"para a próxima vez"],
            )

    detail = f"procurei ao vivo em: {', '.join(visited)}"
    if skipped_submenus:
        detail += ("; não entrei em (submenu ainda não confirmado por "
                   "revisão humana): " + ", ".join(sorted(set(skipped_submenus))))

    return ToolResult(
        tool=tool.name, ok=True, kind="field", value=None, label=term,
        steps=steps,
        notes=[f"{find_setting_mod.NOT_EXIST} (varredura ao vivo, sem "
               f"índice): {term!r}", detail],
    )


EXPLORE_SETTING = register(Tool(
    name="explore_setting",
    question=(
        "Procura QUALQUER ajuste da BIOS pelo nome, AO VIVO na tela real "
        "(sem depender de indice pre-colhido) -- rolando cada pagina do "
        "menu principal e comparando os rotulos lidos contra o termo. Use "
        "SO depois que find_setting responder que o ajuste nao existe: "
        "essa tool e mais lenta (varre paginas inteiras) e existe "
        "exatamente para o caso em que a resposta esta na tela mas nunca "
        "foi colhida no indice. Nao entra em submenus nao confirmados por "
        "revisao humana, nem em save_and_exit. E SOMENTE LEITURA."
    ),
    reader=None,
    router=_explore_setting,
    restore=False,
    params={
        "term": {
            "type": "string",
            "description": ("Nome do ajuste procurado, o mais proximo "
                            "possivel de como a BIOS o escreve -- ex.: "
                            "'System Time', 'Fast Boot'."),
        },
        "question": {
            "type": "string",
            "description": ("A pergunta original do operador, palavra por "
                            "palavra. Opcional, usada para a guarda de "
                            "somente-leitura."),
        },
    },
))

# Mesmo motivo de find_setting.py: `term` obrigatorio, `question` nao.
EXPLORE_SETTING.required_params = ["term"]
