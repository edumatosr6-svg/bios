"""Offline checks for the tools layer, driven by real capture fixtures.

Runs with no camera and no cable: a `FakeBios` stands in for the machine
under test, serving real perception contracts and moving a simulated
cursor when a key is "pressed". That is enough to exercise everything
that is not the hardware itself -- cursor resolution, label/value
pairing, the menu walk, and the two safety guards.

    py -3.13 test_biostools.py

Contracts are produced once from the fixtures in `captures/` and cached
next to this file, because each one costs a full OCR pass.
"""
import copy
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2

from biostools import assistant, navigate, run_tool, screen
from biostools.session import Reading

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".biostools_cache")

# The Advanced page's entry list, with 'Hardware Monitor' under the cursor.
MENU_SCREEN = "positivo_advanced_hardware-monitor"
# The Hardware Monitor page itself, with the sensor readings.
READINGS_SCREEN = "positivo_advanced_cpu-overheat"
# The Main page, captured live off the HDMI card at 1280x720 -- unlike the
# two above, which are 4K photographs of a monitor. Keeping both input
# kinds in the suite is deliberate: hard-edged digital capture and soft
# camera photos stress the geometry differently.
MAIN_SCREEN = "positivo_main_live"

# What a person sees in the Positivo sidebar. 'POSITIVO' and 'Setup' are
# the logo: OCR puts them in the same column and the engine groups them
# with the menu, but the cursor never lands on them.
#
# Spelled as MENU_SCREEN's OCR read it. The other fixture reads the same
# entry as 'Securlty' -- the two captures disagree, which is exactly why
# text matching is normalised and fuzzy rather than exact.
NAV_ENTRIES = ["Main", "Advanced", "Security", "Boot", "Save & Exit", "Event Log"]

_failures = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"       esperado: {want!r}")
        print(f"       obtido  : {got!r}")
        _failures.append(label)
    return ok


def check_that(label, condition, detail=""):
    print(f"  {'ok  ' if condition else 'FAIL'} {label}")
    if not condition:
        if detail:
            print(f"       {detail}")
        _failures.append(label)
    return condition


def contract_for(stem):
    """Perceive a fixture once, then reuse the cached contract."""
    os.makedirs(CACHE, exist_ok=True)
    cached = os.path.join(CACHE, f"{stem}.json")
    if os.path.exists(cached):
        with open(cached, encoding="utf-8") as f:
            return json.load(f)

    image = path = None
    for ext in (".jpg", ".png"):
        path = os.path.join("captures", stem + ext)
        image = cv2.imread(path)
        if image is not None:
            break
    if image is None:
        sys.exit(f"fixture ausente: captures/{stem}.[jpg|png]")

    from perception import perceive

    print(f"  (percebendo {stem} pela primeira vez, leva alguns segundos...)")
    contract = perceive(frames=[image], view="both").contract
    with open(cached, "w", encoding="utf-8") as f:
        json.dump(contract, f)
    return contract


class FakeBios:
    """A stand-in for the machine: serves contracts, moves a cursor.

    The cursor is simulated by rewriting the contract's `states` so the
    entry it sits on carries `focused` -- the same shape E7 emits from the
    S6_border channel. `wrap` chooses between a menu that cycles round and
    one that stops at its ends; both exist in real BIOSes and the walk has
    to handle each.
    """

    def __init__(self, contract, entries=NAV_ENTRIES, index=1, wrap=True,
                 opens_to=None, frozen=False, simulate_nav=False):
        self.contract = contract
        self.entries = entries
        self.index = index
        self.wrap = wrap
        self.opens_to = opens_to
        self.frozen = frozen  # cursor never moves, whatever is pressed
        # Off by default so the fixture's own measured states are served
        # untouched. Turned on only to exercise the sidebar walk, where a
        # moving cursor is the whole point.
        self.simulate_nav = simulate_nav
        self.keys = []
        self.opened = False

    def _ids_by_text(self, full):
        return {p["content"]: p["id"] for p in full.get("primitives", ())
                if p.get("content")}

    def read_stable(self, timeout=None):
        contract = self.opens_to if (self.opened and self.opens_to) else self.contract
        full = copy.deepcopy(contract["full"])
        if self.simulate_nav and not self.opened:
            ids = self._ids_by_text(full)
            target = ids.get(self.entries[self.index])
            full["states"] = [{
                "element_id": target, "class_id": "cFAKE", "name": "focused",
                "channels": ["S6_border"], "magnitude": 9.0, "confidence": 0.9,
                "evidence": {},
            }] if target else []
        return Reading(full=full, digest=contract["digest"], frame=None,
                       captured_at="test")

    def read_cursor(self, timeout=None):
        """The legacy-shaped result navigation reads.

        Synthesised from the same contract `read_stable` serves, so the
        simulated cursor cannot drift between the two views. Marks
        `highlighted` exactly where the contract (or the simulation) says
        the cursor is -- which is what `selection.py` would have produced
        on the real frame.
        """
        reading = self.read_stable()
        full = reading.full
        marked = {s["element_id"] for s in full.get("states", ())
                  if s["name"] in ("focused", "selected")}
        lines = []
        for prim in full.get("primitives", ()):
            if not prim.get("content"):
                continue
            g = prim["geometry"]
            lines.append({
                "text": prim["content"],
                "bbox": {"left": g["x"], "top": g["y"],
                         "width": g["w"], "height": g["h"]},
                "highlighted": prim["id"] in marked,
                "region": "menu_column",
            })
        lines.sort(key=lambda l: (l["bbox"]["top"], l["bbox"]["left"]))
        return {"blocks": [{"block_num": 0, "lines": lines}]}

    def press(self, key):
        self.keys.append(key)
        if key == "enter":
            self.opened = True
            return
        if self.frozen:
            return
        delta = {"down": 1, "up": -1}.get(key, 0)
        if not delta:
            return
        nxt = self.index + delta
        if self.wrap:
            self.index = nxt % len(self.entries)
        else:
            self.index = max(0, min(len(self.entries) - 1, nxt))


def test_cursor_resolution(menu):
    print("\nresolucao de cursor (o que fact_summary nao ve)")
    views = {v.group_id: v for v in screen.group_views(menu["full"])}

    nav = [v for v in views.values() if v.hint == "nav_menu"]
    check("existe exatamente um nav_menu", len(nav), 1)
    check("aba ativa no nav_menu", nav[0].selected.text if nav[0].selected else None,
          "Advanced")

    focused = [v for v in views.values()
               if v.hint == "settings_list" and v.focused]
    check_that("item focado achado no settings_list", len(focused) == 1,
               f"grupos com foco: {[v.group_id for v in focused]}")
    if focused:
        check("item focado", focused[0].focused.text, "Hardware Monitor")

    undetermined = [v for v in views.values() if v.status == "undetermined"]
    check_that("abstencao E7 elevada ate o grupo dono", len(undetermined) == 1,
               f"grupos indeterminados: {[v.group_id for v in undetermined]}")

    # The distinction the architecture spec calls the most dangerous to
    # lose: "nothing is marked" and "could not tell" must not collapse.
    statuses = {v.status for v in views.values()}
    check_that("os tres estados coexistem numa tela so",
               {"focused", "undetermined"} <= statuses, f"status: {statuses}")


def test_field_reading(readings):
    print("\nleitura de campo rotulado")
    full = readings["full"]

    temp = screen.field_value(full, "CPU Temperature",
                              pattern=r"-?\d+(?:\.\d+)?\s*(?:°|deg)?\s*[cf]\b")
    check("valor da temperatura", temp.parsed, "61C")
    check_that("linha crua preservada para auditoria", "CPU Temperature" in temp.row,
               temp.row)

    fan = screen.field_value(full, "CPU Fan Speed", pattern=r"\d+\s*RPM")
    check("valor da rotacao", fan.parsed, "3098 RPM")

    check("rotulo inexistente devolve None",
          screen.field_value(full, "Nao Existe"), None)

    pairs = screen.field_pairs(full, exclude_ids=screen.nav_element_ids(full))
    check("pares rotulo/valor da tela", pairs,
          {"CPU Temperature": "61C", "CPU Fan Speed": "3098 RPM"})


class _FakeLLM:
    """A Lemonade-shaped server that plays back scripted `message` dicts in
    order (the same shape `choices[0].message` has on the real endpoint --
    either `{"tool_calls": [...]}` or `{"content": "..."}`), so a test
    controls exactly what "the model" does across a multi-round tool-calling
    conversation without needing the real NPU box or a network round trip.
    """

    def __init__(self, script, port):
        self.calls = []
        script_ = script

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                message = script_[min(len(self._server_calls()), len(script_) - 1)]
                self._server_calls().append(message)
                payload = json.dumps({"choices": [{"message": message}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

            def _server_calls(self):
                return outer.calls

        outer = self
        self._httpd = HTTPServer(("127.0.0.1", port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        self.port = port

    def close(self):
        self._httpd.shutdown()


def _tool_call_message(call_id, name):
    return {"tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": name, "arguments": "{}"}}]}


def _content_message(text):
    return {"content": text}


def test_assistant_catches_a_hallucinated_value(menu, readings):
    print("\nassistente: chama tools, narra, e pega o modelo mentindo o valor")

    # Cenario 1: uma tool, narracao fiel -- a frase do modelo deve ser
    # usada como esta, porque contem o valor verbatim.
    llm = _FakeLLM([
        _tool_call_message("call_1", "cpu_temperature"),
        _content_message("A temperatura da CPU esta em 61C no momento."),
    ], port=18101)
    try:
        bios = FakeBios(menu, opens_to=readings)
        r = assistant.ask("qual a temperatura da cpu?", bios, port=18101)
        check("uma tool chamada, a certa", [c.tool for c in r.calls], ["cpu_temperature"])
        check("narracao fiel foi aceita", r.narrated, True)
        check_that("resposta contem o valor real", "61C" in r.answer, r.answer)
    finally:
        llm.close()

    # Cenario 2: o CASO QUE IMPORTA. O modelo troca 61C por 65C ao narrar
    # -- o mesmo tipo de distorcao medido de verdade contra o modelo real
    # (61C -> 65C num teste ao vivo desta sessao; extract.py mediu 2026 ->
    # 20026 antes). Isto tem que ser pego e descartado, nao mostrado ao
    # usuario como se fosse a leitura real.
    llm = _FakeLLM([
        _tool_call_message("call_1", "cpu_temperature"),
        _content_message("A temperatura da CPU esta em 65C, um pouco alta."),
    ], port=18102)
    try:
        bios = FakeBios(menu, opens_to=readings)
        r = assistant.ask("qual a temperatura da cpu?", bios, port=18102)
        check("narracao alterada foi REJEITADA", r.narrated, False)
        check_that("caiu para o valor verificado (61C)", "61C" in r.answer, r.answer)
        check_that("o valor inventado NAO aparece na resposta",
                   "65C" not in r.answer, r.answer)
    finally:
        llm.close()

    # Cenario 3: nenhuma tool cobre a pergunta -- o modelo responde direto,
    # sem chamar nada. Vazio-verdadeiro na verificacao (nao ha valor a
    # conferir), entao a frase do modelo passa como esta.
    llm = _FakeLLM([_content_message(
        "Nao tenho como responder isso com as informacoes da BIOS."
    )], port=18103)
    try:
        bios = FakeBios(menu, opens_to=readings)
        r = assistant.ask("qual a cor do gabinete?", bios, port=18103)
        check("nenhuma tool foi chamada", r.calls, [])
        check_that("resposta de recusa foi repassada", "responder" in r.answer, r.answer)
    finally:
        llm.close()

    # Cenario 4: o modelo pede uma tool que nao existe -- tem que ficar
    # registrado como erro daquela chamada, distinto de "a BIOS nao tinha
    # a resposta", e o loop continua (o modelo ve o erro e pode desistir).
    llm = _FakeLLM([
        _tool_call_message("call_1", "temperatura_do_processador"),
        _content_message("Nao consegui obter essa informacao."),
    ], port=18104)
    try:
        bios = FakeBios(menu, opens_to=readings)
        r = assistant.ask("qual a temperatura da cpu?", bios, port=18104)
        check_that("chamada de tool inexistente registrada com erro",
                   len(r.calls) == 1 and r.calls[0].error is not None,
                   f"calls={r.calls}")
    finally:
        llm.close()

    # Cenarios 5-7 testam a verificacao multi-valor (assistant._finish)
    # diretamente, com ToolResult sinteticos, em vez de passar por
    # navegacao simulada -- bios_info precisa da tela "main", que este
    # FakeBios (montado sobre a tela Advanced) nao alcanca, e o que
    # importa aqui e a matematica da verificacao, nao a navegacao dela
    # (ja coberta em test_bios_info). Confirmado antes de escrever assim:
    # rodar bios_info contra este FakeBios de fato falha em navegar
    # (not_found_after_full_cycle) -- ir por ask() faria estes cenarios
    # testarem sem querer "bios_info falhou" em vez de "dois valores".
    from biostools.assistant import ToolCall, _finish
    from biostools.registry import ToolResult

    cpu_call = ToolCall(tool="cpu_temperature", result=ToolResult(
        tool="cpu_temperature", ok=True, kind="field",
        label="CPU Temperature", value="61C",
    ))
    bios_call = ToolCall(tool="bios_info", result=ToolResult(
        tool="bios_info", ok=True, kind="fields",
        values={"BIOS Version": "7.2.4.XD22CPG7.I219V.P",
                "Platform BIOS Type": "RaptorLake P I219-V"},
    ))

    # Cenario 5: os dois valores aparecem na frase -> aceita.
    r = _finish("qual a temperatura da cpu e a versao da bios?", [cpu_call, bios_call],
                "A CPU esta a 61C, a BIOS Version e 7.2.4.XD22CPG7.I219V.P "
                "e a plataforma e RaptorLake P I219-V.")
    check("narracao com os tres valores foi aceita", r.narrated, True)

    # Cenario 6: um valor fica de fora -- tem que cair para o texto
    # deterministico, mesmo os outros estando certos.
    r = _finish("qual a temperatura da cpu e a versao da bios?", [cpu_call, bios_call],
                "A CPU esta a 61C e a BIOS Version e 7.2.4.XD22CPG7.I219V.P.")
    check("narracao parcial (faltando 1 de 3 valores) foi REJEITADA", r.narrated, False)
    check_that("fallback traz os tres valores",
               all(v in r.answer for v in
                   ("61C", "7.2.4.XD22CPG7.I219V.P", "RaptorLake P I219-V")),
               r.answer)

    # Cenario 7: uma listagem de menu nunca e narrada pela LLM, mesmo com
    # todo o texto do modelo batendo -- nao ha um "valor" unico contra o
    # qual conferir uma lista parafraseada, entao a LLM poderia inventar
    # ou esquecer uma opcao sem nada aqui para pegar.
    entries_call = ToolCall(tool="main_menu", result=ToolResult(
        tool="main_menu", ok=True, kind="entries",
        entries=["Main", "Advanced", "Security", "Boot", "Save & Exit", "Event Log"],
    ))
    r = _finish("quais opcoes tem no menu?", [entries_call],
                "O menu principal tem: Main, Advanced, Security, Boot, "
                "Save & Exit, Event Log.")
    check("listagem de menu nunca e narrada pela LLM, mesmo perfeita", r.narrated, False)
    check_that("fallback usa a lista verificada pela caminhada",
               "Event Log" in r.answer, r.answer)


def test_label_aliases():
    print("\nrotulos canonicos: conceito separado da grafia da tela")
    from biostools import labels

    ROTULOS = labels.field("cpu_temperature")

    # Um conceito que nao existe tem que estourar na declaracao da tool,
    # em tempo de import -- nao no meio de uma navegacao numa maquina real.
    for kind, bad in ((labels.field, "temperatura_da_cpu"),
                      (labels.screen, "hardwaremonitor")):
        try:
            kind(bad)
            check_that(f"canonico invalido {bad!r} recusado", False)
        except labels.UnknownLabel:
            check_that(f"canonico invalido {bad!r} recusado", True)

    for spelling in ("CPU Temperature", "� CPU Temperature", "CPU  Temperature",
                     "CPU Temp", "CPU Temp.", "Processor Temperature",
                     "CPU Package Temperature"):
        check_that(f"casa {ascii(spelling)}", screen.match_score(ROTULOS, spelling) > 0)

    # A metade que protege contra erro silencioso: um campo vizinho na
    # mesma tela nunca pode passar por temperatura da CPU. Reportar a
    # temperatura do sistema como sendo a da CPU e um erro que um operador
    # age em cima; "nao achei" e barulhento e inofensivo.
    for other in ("System Temperature", "CPU Fan Speed", "PCH Temperature",
                  "Memory Temperature"):
        check_that(f"NAO casa {ascii(other)}", screen.match_score(ROTULOS, other) == 0)

    # O usuario pergunta em portugues; a tela da BIOS e em ingles. Traduzir
    # a pergunta e trabalho da camada de tool-calling, nao do matcher --
    # aceitar PT-BR aqui so criaria falso casamento sem servir para nada.
    check_that("nao tenta casar a pergunta do usuario com a tela",
               screen.match_score(ROTULOS, "Temperatura da CPU") == 0)


def test_main_info(main):
    print("\ntool main_info: pares da tela Main")
    full = main["full"]
    pairs = screen.field_pairs(full, exclude_ids=screen.nav_element_ids(full))

    check("versao da BIOS", pairs.get("BIOS Version"), "7.2.4.XD22CPG7.I219V.P")
    check("versao do EC", pairs.get("EC FW Version"), "01.22")
    check("data de build", pairs.get("BIOS Build Date (MM/DD/YYYY)"),
          "06/26/2026 16:01:12")
    check("nivel de acesso", pairs.get("Access Level"), "Administrator")
    check("total de campos", len(pairs), 11)

    # The three ways the surrounding chrome used to leak in, each now
    # blocked by a different filter -- see field_pairs' docstring.
    check_that("barra lateral fora dos rotulos",
               not {"Main", "Advanced", "Setup", "Security"} & set(pairs),
               f"rotulos: {sorted(pairs)}")
    check_that("caixa de ajuda da direita fora dos valores",
               not any(v in ("Previous", "Optimized", "Back")
                       for v in pairs.values()),
               f"valores: {sorted(pairs.values())}")

    # The whole point of reading every pair instead of a fixed label list.
    bios_fields = [k for k in pairs if "BIOS" in k or "EC " in k]
    check_that("achou os campos de versao sem ter que nomea-los",
               len(bios_fields) >= 5, f"campos: {bios_fields}")


def test_bios_info(main):
    print("\ntool bios_info: versao, build date e plataforma nomeados")
    full = main["full"]
    from biostools import labels

    version = screen.field_value(full, labels.field("bios_version"))
    check("versao da BIOS", version.value, "7.2.4.XD22CPG7.I219V.P")

    build_date = screen.field_value(full, labels.field("bios_build_date"))
    check("data de build", build_date.value, "06/26/2026 16:01:12")

    platform = screen.field_value(full, labels.field("platform_type"))
    check("tipo de plataforma", platform.value, "RaptorLake P I219-V")

    # Regressao: sem os filtros de regiao/distancia que field_pairs ja
    # tinha, field_value juntava a caixa de icones da direita ('Previous
    # Values') ao valor da linha 'BIOS Version', porque ela cai dentro da
    # tolerancia vertical da linha. Trava as duas metades: o valor certo
    # (acima) e a poluicao ausente (aqui).
    check_that("caixa de icones da direita nao contamina o valor",
               "Previous" not in version.value, version.value)


def test_cpu_temperature(menu, readings):
    print("\ntool cpu_temperature, fim a fim")
    bios = FakeBios(menu, opens_to=readings)
    result = run_tool("cpu_temperature", bios)
    check("resposta", result.value, "61C")
    # "left"/"right" sao sempre pressionados uma vez por perna com
    # focus_key (entregam o foco do teclado a sidebar/conteudo antes de
    # andar -- ver Step.focus_key), mesmo quando o cursor ja estava no
    # alvo; so as setas de navegacao propriamente ditas (up/down) devem
    # ficar a zero aqui.
    check("cursor ja estava no alvo, nenhuma navegacao gasta",
          [k for k in bios.keys if k in ("up", "down")], [])
    check("focus_key (left) da perna 1 foi pressionado", bios.keys.count("left"), 1)
    check("focus_key (right) da perna 2 foi pressionado", bios.keys.count("right"), 1)
    check("abriu com enter", bios.keys.count("enter"), 1)
    # Without this the tool is single-use: it would leave the BIOS inside
    # the submenu, where the entry it navigates to no longer exists.
    check("fechou o que abriu (repetivel)", bios.keys.count("esc"), 1)
    check("esc veio depois do enter", bios.keys[-1], "esc")


def test_menu_walk(menu):
    print("\ntool main_menu: caminhada pelo menu")
    for wrap in (True, False):
        rotulo = "menu que da a volta" if wrap else "menu que para nas pontas"
        bios = FakeBios(menu, index=3, wrap=wrap, simulate_nav=True)
        result = run_tool("main_menu", bios)
        check(f"{rotulo}: todas as opcoes achadas",
              sorted(result.entries), sorted(NAV_ENTRIES))
        check_that(f"{rotulo}: logo excluido",
                   not any(t in result.entries for t in ("POSITIVO", "Setup")),
                   f"entradas: {result.entries}")
        check_that(f"{rotulo}: logo reportado como nao-opcao",
                   any("POSITIVO" in n for n in result.notes),
                   f"notas: {result.notes}")


def test_walk_survives_stuck_cursor(menu):
    print("\ntool main_menu: cursor que nao anda")
    bios = FakeBios(menu, frozen=True, simulate_nav=True)
    result = run_tool("main_menu", bios)
    check_that("ainda responde com o que a tela mostra", result.ok,
               f"erro: {result.error}")
    check_that("marca a lista como nao confirmada",
               any("sem confirmacao" in n for n in result.notes),
               f"notas: {result.notes}")


def test_safety_guards(menu):
    print("\nguardas de seguranca")
    bios = FakeBios(menu, frozen=True, simulate_nav=True)
    outcome = navigate.move_to(bios, "Nao Existe Este Menu",
                               hint="nav_menu", max_steps=20)
    check("alvo inexistente para por ciclo", outcome.reason, navigate.CYCLED)
    check_that("para em ~1 tecla, nao no teto de 20", len(bios.keys) <= 2,
               f"teclas enviadas: {bios.keys}")

    blind = copy.deepcopy(menu)
    blind["full"]["states"] = []
    quiet = FakeBios(blind)
    quiet.read_stable = lambda timeout=None: Reading(
        full=blind["full"], digest=blind["digest"], frame=None, captured_at="t")
    outcome = navigate.move_to(quiet, "Main", hint="nav_menu")
    check("cursor indeterminado e reportado", outcome.reason, navigate.BLIND)
    check("nenhuma tecla enviada as cegas", quiet.keys, [])


def main():
    print("carregando fixtures...")
    menu = contract_for(MENU_SCREEN)
    readings = contract_for(READINGS_SCREEN)
    main = contract_for(MAIN_SCREEN)

    test_cursor_resolution(menu)
    test_label_aliases()
    test_field_reading(readings)
    test_main_info(main)
    test_bios_info(main)
    test_cpu_temperature(menu, readings)
    test_assistant_catches_a_hallucinated_value(menu, readings)
    test_menu_walk(menu)
    test_walk_survives_stuck_cursor(menu)
    test_safety_guards(menu)

    print()
    if _failures:
        print(f"{len(_failures)} falha(s): {', '.join(_failures)}")
        return 1
    print("tudo passou")
    return 0


if __name__ == "__main__":
    sys.exit(main())
