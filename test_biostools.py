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
import numpy as np

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


def legacy_reading_for(stem):
    """The legacy `selection.py`-annotated OCR result for a saved frame --
    what `BiosSession.read_cursor()` returns, minus the camera.

    Cached like `contract_for`, but under a different suffix: this is OCR +
    `selection.py`, not a perception contract, and the two must never be
    confused for the same fixture.
    """
    os.makedirs(CACHE, exist_ok=True)
    cached = os.path.join(CACHE, f"{stem}_legacy.json")
    if os.path.exists(cached):
        with open(cached, encoding="utf-8") as f:
            return json.load(f)

    path = os.path.join("captures", stem + ".jpg")
    frame = cv2.imread(path)
    if frame is None:
        sys.exit(f"fixture ausente: {path}")

    from ocr import DEFAULT_ENGINE, create_ocr_engine
    from selection import annotate_selection

    print(f"  (lendo {stem} pelo caminho legado pela primeira vez...)")
    result = create_ocr_engine(DEFAULT_ENGINE).read(frame)
    result["screen_bg_color"] = annotate_selection(frame, result["blocks"])
    with open(cached, "w", encoding="utf-8") as f:
        json.dump(result, f)
    return result


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
        # Each ENTER descends one level, so the screens form a stack, not a
        # single before/after pair. Modelling it as a pair hid the real
        # structure: reaching a top-level page needs its own ENTER (the
        # sidebar cursor moving does NOT switch the page on this BIOS --
        # measured 2026-08-24), so a tool that opens a submenu presses
        # ENTER twice and passes through two different screens.
        # `opens_to` accepts a list for that; a bare contract still means
        # "one level down".
        chain = opens_to if isinstance(opens_to, list) else [opens_to]
        self.stack = [contract] + [c for c in chain if c is not None]
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
        self.opened = 0  # how many ENTERs deep we are in `self.stack`

    def _ids_by_text(self, full):
        return {p["content"]: p["id"] for p in full.get("primitives", ())
                if p.get("content")}

    def read_stable(self, timeout=None):
        contract = self.stack[min(self.opened, len(self.stack) - 1)]
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
        # A frame whose "Setup" icon region reads as filled, so navigation's
        # anchor check passes and the ROUTE logic gets exercised here. The
        # pixel test itself is not faked into passing -- it is checked
        # against real captures in test_setup_icon_anchor, which is the
        # only honest way to cover a measurement of real pixels.
        # Sized from the contract's own surface, not a fixed 1280x720:
        # these fixtures are 3840-wide photographs, and a frame in a
        # different coordinate space than the line boxes it accompanies
        # makes every geometry query (sidebar limit, icon box) answer
        # about the wrong part of the screen.
        surface = full.get("surface") or {}
        width = int(surface.get("width") or 1280)
        height = int(surface.get("height") or 720)
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        # Roughly the filled-disc coverage a real anchored frame shows
        # (~0.43); an all-white box would instead read as "obscured".
        x0, y0, x1, y1 = navigate._SETUP_ICON_BOX
        frame[int(y0 * height):int(y0 * height + (y1 - y0) * height * 0.6),
              int(x0 * width):int(x1 * width)] = 255
        return {"blocks": [{"block_num": 0, "lines": lines}], "frame": frame}

    def press(self, key):
        self.keys.append(key)
        if key == "enter":
            self.opened += 1
            return
        if key == "esc":
            self.opened = max(0, self.opened - 1)
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
        # Cada payload recebido, para um teste poder afirmar o que foi
        # ENVIADO ao modelo (system prompt, tools), nao so o que ele
        # respondeu. Antes o corpo era lido e jogado fora, entao a
        # ausencia de system prompt em `ask()` -- a causa raiz do
        # "despejou a tela em vez de responder sim/nao", 2026-08-28 --
        # nao tinha como ser pega por nenhum teste.
        self.payloads = []
        script_ = script

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                try:
                    outer.payloads.append(json.loads(body.decode("utf-8")))
                except (ValueError, UnicodeDecodeError):
                    outer.payloads.append(None)
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
        bios = FakeBios(menu, opens_to=[menu, readings])
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
        bios = FakeBios(menu, opens_to=[menu, readings])
        r = assistant.ask("qual a temperatura da cpu?", bios, port=18102)
        check("narracao alterada foi REJEITADA", r.narrated, False)
        check_that("caiu para o valor verificado (61C)", "61C" in r.answer, r.answer)
        check_that("o valor inventado NAO aparece na resposta",
                   "65C" not in r.answer, r.answer)
    finally:
        llm.close()

    # Cenario 3: nenhuma tool cobre a pergunta -- o modelo desiste sem
    # chamar nada. O loop insiste uma vez (ver Cenario 3b), o
    # _FakeLLM aqui so tem UMA mensagem no script e repete a ultima em
    # toda chamada extra, entao a segunda rodada ve a MESMA recusa de
    # novo -- exatamente o que um modelo real faria para uma pergunta que
    # nenhuma tool cobre de verdade. So depois da insistencia o loop
    # aceita: vazio-verdadeiro na verificacao (nao ha valor a conferir),
    # entao a frase do modelo passa como esta.
    llm = _FakeLLM([_content_message(
        "Nao tenho como responder isso com as informacoes da BIOS."
    )], port=18103)
    try:
        bios = FakeBios(menu, opens_to=[menu, readings])
        r = assistant.ask("qual a cor do gabinete?", bios, port=18103)
        check("nenhuma tool foi chamada", r.calls, [])
        check_that("resposta de recusa foi repassada", "responder" in r.answer, r.answer)
    finally:
        llm.close()

    # Cenario 3b: o BUG QUE ESTE COMMIT CORRIGE, ao vivo em 2026-08-28 --
    # "qual a hora do sistema?" tinha "System Time" no indice de
    # find_setting, e o modelo mesmo assim respondeu "nao e possivel"
    # SEM chamar nada, passando sem verificacao pelo caminho vazio-
    # verdadeiro do Cenario 3 (errado ali, porque a pergunta TEM
    # resposta). Aqui a segunda rodada chama cpu_temperature em vez de
    # find_setting -- so para provar que o loop de fato insiste e a
    # tool chamada na volta e verificada normalmente, sem precisar
    # arrastar o indice real de find_setting para este teste (esse ja
    # tem cobertura propria).
    llm = _FakeLLM([
        _content_message("Nao e possivel determinar isso com as ferramentas disponiveis."),
        _tool_call_message("call_1", "cpu_temperature"),
        _content_message("A temperatura da CPU esta em 61C no momento."),
    ], port=18108)
    try:
        bios = FakeBios(menu, opens_to=[menu, readings])
        r = assistant.ask("qual a temperatura da cpu?", bios, port=18108)
        check("o loop insistiu -- a tool acabou sendo chamada",
              [c.tool for c in r.calls], ["cpu_temperature"])
        check("resposta apos a insistencia foi verificada", r.narrated, True)
        check_that("valor real aparece", "61C" in r.answer, r.answer)
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
        bios = FakeBios(menu, opens_to=[menu, readings])
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

    # Cenarios 8-9: `goto_screen` (AllFields, open_ended=True) contra uma
    # pergunta sobre UM campo entre varios lidos -- o caso real relatado
    # 2026-08-28 ("fast boot esta habilitado?" caindo sempre no dump bruto
    # porque a narracao nunca citava os outros 4 campos irrelevantes, ex.:
    # 'BIOS POST Logo Delay'). ANY-must-appear substitui ALL-must-appear
    # so para leituras abertas -- ver ToolResult.open_ended e
    # assistant._required_values.
    boot_call = ToolCall(tool="goto_screen", result=ToolResult(
        tool="goto_screen", ok=True, kind="fields", open_ended=True,
        values={"BIOS POST Logo Delay": "Standard", "Bootup NumLock State": "off",
                "NumLock Disabled During Pre-Boot": "Enabled",
                "Fast Boot": "Enabled",
                "POPUP Boot Menu Hotkey [F11]": "Enabled"},
    ))

    r = _finish("o fast boot esta habilitado?", [boot_call],
                "Sim, o campo Fast Boot esta como Enabled.")
    check_that("cita SO o campo relevante de uma leitura aberta -> aceita",
               r.narrated, r.answer)

    r = _finish("o fast boot esta habilitado?", [boot_call],
                "Nao, o Fast Boot esta Disabled no momento.")
    check("narracao que nao cita NENHUM valor real da leitura aberta -> REJEITADA",
          r.narrated, False)
    # 'Disabled' aparece no dump bruto -- mas so como parte do ROTULO
    # 'NumLock Disabled During Pre-Boot', nunca como o VALOR de 'Fast
    # Boot' (que e 'Enabled'). E essa distincao que importa: a mentira do
    # modelo nao vira a resposta mostrada.
    check_that("fallback nao afirma 'Fast Boot: Disabled'",
               "Fast Boot                        : Disabled" not in r.answer, r.answer)
    check_that("fallback mostra o valor real de Fast Boot",
               "Fast Boot                        : Enabled" in r.answer, r.answer)


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
    bios = FakeBios(menu, opens_to=[menu, readings])
    result = run_tool("cpu_temperature", bios)
    check("resposta", result.value, "61C")
    # A perna da barra lateral ancora e conta, sempre: N+2 "up" para
    # encostar no topo (a lista nao da a volta) e indice+1 "down" para
    # descer ate a entrada. Nao ha atalho de "o cursor ja estava la" --
    # essa era uma economia do caminho que observava o cursor, e ele foi
    # removido justamente por nao conseguir distinguir a barra do cursor
    # da barra da pagina ativa. Pagar 8 teclas para ter certeza e melhor
    # que economizar 8 e apertar ENTER no lugar errado.
    ups = [k for k in bios.keys if k == "up"]
    downs = [k for k in bios.keys if k == "down"]
    check("ancorou no topo antes de contar", len(ups), len(NAV_ENTRIES) + 2)
    check_that("contou ate 'advanced' (indice 1 -> 2 down) mais a perna 2",
               len(downs) >= 2, f"downs: {downs}")
    check("focus_key (left) da perna 1 foi pressionado", bios.keys.count("left"), 1)
    # Nenhum "right": o ENTER da perna 1 ja entrega o foco ao conteudo da
    # pagina aberta. O "right" que existia aqui era compensacao para a
    # perna 1 nao abrir a pagina (activate=False) e deixar o foco na barra
    # lateral; com aquilo corrigido, ele passou a ATRAPALHAR -- levaria o
    # foco para a coluna de icones da direita. Ver cpu_temperature.py.
    check("nenhum focus_key na perna 2", bios.keys.count("right"), 0)
    # DOIS enters, um por nivel: o primeiro abre a pagina "Advanced" a
    # partir da barra lateral, o segundo abre "Hardware Monitor" dentro
    # dela. Isto era 1 ate 2026-08-24, quando a perna da barra lateral
    # tinha activate=False -- o cursor chegava em Advanced mas a pagina
    # exibida continuava a anterior, e a perna 2 procurava "Hardware
    # Monitor" no conteudo da tela errada. Era essa a falha de "estou na
    # Main e nao consigo ir para a Advanced"; ver captures/handshake/.
    check("abriu com enter, um por nivel", bios.keys.count("enter"), 2)
    # Without this the tool is single-use: it would leave the BIOS inside
    # the submenu, where the entry it navigates to no longer exists.
    check("fechou o que abriu (repetivel)", bios.keys.count("esc"), 2)
    check("esc veio depois do enter", bios.keys[-1], "esc")


def test_goto_screen(menu):
    print("\ntool goto_screen: chega numa tela do menu principal por nome, sem rota fixa")

    # A tela chega no ARGUMENTO da chamada, nao numa Step declarada em
    # tempo de import -- entao o unico jeito de exercitar isto de ponta a
    # ponta e uma tela cujo fixture ja existe. 'advanced' e a propria
    # pagina em que `menu` foi capturado, entao um unico ENTER (ancorar,
    # contar ate o indice 1, apertar enter) basta para "chegar".
    bios = FakeBios(menu, opens_to=[menu], simulate_nav=True)
    result = run_tool("goto_screen", bios, args={"screen": "advanced"})
    check_that("chegou", result.ok, result.error)
    check("um enter, um nivel", bios.keys.count("enter"), 1)
    # restore=False e o ponto do tool: ao contrario de cpu_temperature
    # (que fecha tudo que abriu), aqui a BIOS deve FICAR na tela pedida.
    check("nao restaurou (ficou na tela)", bios.keys.count("esc"), 0)
    check("opened continua 1 (nao fechou)", bios.opened, 1)

    # Tolerante a maiuscula/minuscula e espaco, mas nunca inventa uma tela
    # que nao esteja em navigate.TOP_LEVEL_SCREENS -- normalizado ANTES de
    # navegar, entao o teste abaixo nao precisa mexer no cursor.
    bios_case = FakeBios(menu, opens_to=[menu], simulate_nav=True)
    result_case = run_tool("goto_screen", bios_case, args={"screen": "Advanced"})
    check_that("aceita grafia com maiuscula", result_case.ok, result_case.error)

    bios_missing = FakeBios(menu, opens_to=[menu], simulate_nav=True)
    result_missing = run_tool("goto_screen", bios_missing, args={})
    check("sem parametro 'screen' -> falha, sem tocar teclado",
          (result_missing.ok, bios_missing.keys), (False, []))

    # 'hardware_monitor' e uma tela CONHECIDA (labels.SCREENS) mas nao e
    # uma entrada de topo da barra lateral -- enter_main_menu_screen nao
    # sabe chegar la direto, entao o tool tem que recusar em vez de tentar
    # e falhar misteriosamente no meio da navegacao.
    bios_nested = FakeBios(menu, opens_to=[menu], simulate_nav=True)
    result_nested = run_tool("goto_screen", bios_nested,
                             args={"screen": "hardware_monitor"})
    check("tela aninhada (nao e topo da barra) -> recusa sem tocar teclado",
          (result_nested.ok, bios_nested.keys), (False, []))

    bios_unknown = FakeBios(menu, opens_to=[menu], simulate_nav=True)
    result_unknown = run_tool("goto_screen", bios_unknown,
                              args={"screen": "nao existe"})
    check("tela desconhecida -> recusa sem tocar teclado",
          (result_unknown.ok, bios_unknown.keys), (False, []))

    # O schema que o assistant.py manda ao modelo tem que anunciar
    # exatamente as telas alcancaveis -- nem mais (o modelo pediria uma
    # tela que o tool vai recusar) nem menos (o modelo nem saberia que
    # pode pedir).
    from biostools import navigate
    from biostools.assistant import _tool_schemas

    schema = next(s for s in _tool_schemas()
                  if s["function"]["name"] == "goto_screen")
    check("enum do parametro 'screen' bate com as telas de topo",
          set(schema["function"]["parameters"]["properties"]["screen"]["enum"]),
          set(navigate.TOP_LEVEL_SCREENS))
    check("'screen' e obrigatorio no schema",
          schema["function"]["parameters"]["required"], ["screen"])


def test_all_fields_scroll_merges_pages():
    print("\nreader AllFields(scroll=True): junta campos que so aparecem depois de rolar")

    # Caso real relatado 2026-08-28: "qual e a boot option 1?" respondeu
    # so com os 5 campos do primeiro frame porque ninguem rolava o painel
    # de conteudo. `screen.field_pairs` e o que qualquer AllFields chama
    # por leitura -- trocado por um dublê aqui porque montar um contrato
    # `full` de verdade so para variar entre leituras nao testaria nada
    # que `field_pairs` em si (ja coberto em test_main_info/test_bios_info)
    # nao cobre; o que este teste verifica e a MECANICA DE ROLAGEM, nao a
    # extracao de pares.
    import biostools.registry as registry_mod
    from biostools.registry import AllFields

    class _FakeSession:
        def __init__(self):
            self.keys = []

        def press(self, key):
            self.keys.append(key)

        def read_stable(self, timeout=None):
            return type("R", (), {"full": {}})()

    seed = {"BIOS POST Logo Delay": "Standard", "Fast Boot": "Enabled"}
    # O que cada tecla "down" revela: a 1a rolagem traz Boot Option #1
    # (novidade), a 2a substitui a tela inteira por #1/#2 (ainda uma
    # novidade, #2), e as duas seguintes nao trazem nada que ja nao
    # estivesse acumulado -- duas leituras iguais seguidas e o sinal de
    # "acabou", pelo `_scroll_and_merge`.
    per_press = [
        {"BIOS POST Logo Delay": "Standard", "Fast Boot": "Enabled",
         "Boot Option #1": "Windows Boot Manager"},
        {"Boot Option #1": "Windows Boot Manager", "Boot Option #2": "USB HDD"},
        {"Boot Option #1": "Windows Boot Manager", "Boot Option #2": "USB HDD"},
        {"Boot Option #1": "Windows Boot Manager", "Boot Option #2": "USB HDD"},
    ]
    calls = {"n": 0}

    def fake_field_pairs(full, exclude_ids=frozenset()):
        i = min(calls["n"], len(per_press) - 1)
        calls["n"] += 1
        return dict(per_press[i])

    original = registry_mod.screen.field_pairs
    registry_mod.screen.field_pairs = fake_field_pairs
    try:
        session = _FakeSession()
        reader = AllFields(scroll=True, max_scroll=10)
        values, steps, notes = reader._scroll_and_merge(session, seed)
    finally:
        registry_mod.screen.field_pairs = original

    check("achou o campo que so aparecia depois de rolar",
          values.get("Boot Option #1"), "Windows Boot Manager")
    check("achou o segundo tambem", values.get("Boot Option #2"), "USB HDD")
    check("nao perdeu os campos do frame inicial", values.get("Fast Boot"), "Enabled")
    check("parou apos duas leituras sem nada novo, nao gastou os 10 do teto",
          steps, 4)
    check("sem aviso de 'pode haver mais' quando parou por fim de lista", notes, [])

    # Segundo cenario: TODA rolagem traz algo novo (lista maior que o
    # teto) -- tem que parar no `max_scroll` e AVISAR, nao voltar
    # silenciosamente como se tivesse lido tudo.
    calls["n"] = 0

    def ever_growing(full, exclude_ids=frozenset()):
        calls["n"] += 1
        return {f"Boot Option #{calls['n']}": f"Device {calls['n']}"}

    registry_mod.screen.field_pairs = ever_growing
    try:
        session2 = _FakeSession()
        reader2 = AllFields(scroll=True, max_scroll=5)
        values2, steps2, notes2 = reader2._scroll_and_merge(session2, {})
    finally:
        registry_mod.screen.field_pairs = original

    check("gastou o teto inteiro (nunca deu stall)", steps2, 5)
    check_that("avisou que pode haver mais campos", bool(notes2), notes2)


def test_ask_sends_a_system_prompt(menu, readings):
    print("\nassistant.ask: manda system prompt instruindo a responder direto")

    # Regressao da causa raiz relatada 2026-08-28: `ask()` montava
    # `messages` com APENAS a pergunta do usuario, sem nenhuma instrucao
    # de como responder -- e o modelo (4B) devolvia a tela inteira em vez
    # de responder a pergunta feita. Medido no endpoint real depois do
    # fix: "o fast boot esta desabilitado ou habilitado?" passou de
    # "O Fast Boot esta **habilitado**." para "Sim, o Fast Boot esta
    # Enabled." -- direto, nomeando o campo, e com o valor literal (logo
    # verificavel sem depender da tabela de sinonimos).
    llm = _FakeLLM([
        _tool_call_message("call_1", "cpu_temperature"),
        _content_message("A temperatura da CPU esta em 61C no momento."),
    ], port=18105)
    try:
        bios = FakeBios(menu, opens_to=[menu, readings])
        assistant.ask("qual a temperatura da cpu?", bios, port=18105)
    finally:
        llm.close()

    check_that("houve pelo menos uma chamada ao modelo", bool(llm.payloads),
               f"payloads={llm.payloads}")
    first = llm.payloads[0]
    roles = [m.get("role") for m in first["messages"]]
    check("a primeira mensagem e o system prompt", roles[0], "system")
    check("a pergunta do usuario vem logo depois", roles[1], "user")

    system_text = first["messages"][0]["content"]
    # Nao trava a redacao exata do prompt (ela vai ser afinada contra o
    # modelo real), so as duas instrucoes que existem por um motivo
    # medido: responder direto, e citar o valor como lido -- esta segunda
    # e o que mantem a verificacao do _finish possivel.
    check_that("instrui a responder com sim/nao quando cabe",
               "Sim" in system_text and "Não" in system_text, system_text)
    check_that("instrui a citar o valor exatamente como lido",
               "EXATAMENTE" in system_text, system_text)


def test_verbatim_accepts_pt_br_toggle_synonyms():
    print("\nassistant._verbatim: aceita traducao PT-BR de Enabled/Disabled etc, "
          "sem afrouxar valores numericos/datas")
    from biostools.assistant import _verbatim

    check("Enabled == habilitado", _verbatim("Enabled", "sim, esta habilitado"), True)
    check("Enabled == ativado", _verbatim("Enabled", "o campo esta ativado"), True)
    check("Disabled == desabilitado",
          _verbatim("Disabled", "nao, esta desabilitado"), True)
    check("Disabled NAO == habilitado (nao inverte o sentido)",
          _verbatim("Disabled", "sim, esta habilitado"), False)
    check("On == ligado", _verbatim("On", "o modo esta ligado"), True)
    check("valor numerico continua exigindo o literal (sem sinonimo)",
          _verbatim("61C", "a cpu esta quente"), False)
    check("valor numerico literal continua batendo normalmente",
          _verbatim("61C", "a cpu esta a 61C"), True)


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


def test_setup_icon_anchor():
    """A ancora de navegacao, medida em frames REAIS (nao simulados).

    O sinal nao esta em texto nenhum: a palavra "Setup" renderiza
    identica com e sem o cursor nela (fg/bg bit a bit iguais, medido).
    O que muda e o icone circular ao lado -- anel quando o cursor esta
    em outro lugar, disco preenchido quando esta nele. E por isso que
    todas as tentativas via OCR erraram: `selection.py` so amostra cor
    dentro de caixa de texto, e isto e um icone.
    """
    print("\nancora de navegacao: icone 'Setup' preenchido vs contornado")
    for stem, expected, what in (
        ("ancora_topo", True, "cursor NA seta (ancorado)"),
        ("agora_fresco", False, "cursor no conteudo"),
        ("na_main", False, "cursor no conteudo, outra pagina"),
    ):
        frame = cv2.imread(os.path.join("captures", "handshake", stem + ".png"))
        if frame is None:
            check_that(f"fixture {stem} presente", False)
            continue
        check(f"{what}", navigate.setup_icon_focused(frame), expected)

    # Um dialogo modal escurece a pagina atras dele, e a regiao do icone
    # some. Isso tem que devolver None ("nao consigo dizer"), nunca False
    # ("nao esta ancorado") -- sao respostas diferentes: a segunda
    # autorizaria apertar mais teclas.
    dialog = cv2.imread(os.path.join("captures", "handshake", "apos_falha.png"))
    if dialog is not None:
        check("dialogo cobrindo a barra -> nao sei dizer",
              navigate.setup_icon_focused(dialog), None)


def test_sidebar_legacy_cursor():
    """Padroes 1 e 3 do P-spec `deteccao-cursor-barra-lateral-instavel-
    entre-frames.md`, travados como fixture -- ver `study_sidebar_stability.py`
    e o P-spec para como/por que estes 3 frames foram escolhidos: 25/25 (padrao
    1), 6/6 e 8/8 (padrao 3, dois pares de itens diferentes) leituras ao vivo
    identicas, ou seja, nao e jitter de captura, e comportamento reproduzivel.
    """
    print("\ncursor legado na barra lateral: padroes 1 e 3")

    # Padrao 1: fundo escuro atras do item ativo -- selection.py acha o
    # cursor direto, sem precisar do fallback.
    reading = legacy_reading_for("positivo_sidebar_pattern1_advanced")
    marked = screen.legacy_cursor(reading)
    check_that("padrao 1: cursor achado direto", marked is not None)
    if marked:
        check("padrao 1: item certo", screen.normalize(marked["text"]), "advanced")

    # Padrao 3: dois itens com texto escuro ao mesmo tempo -- a pagina
    # aberta (Advanced) e o item onde o cursor esta agora (Security),
    # quando diferem. A trava MAX_TEXT_COLOR_OUTLIERS=1 de selection.py
    # abstem por design (dois candidatos, nenhuma base para escolher as
    # cegas); e o proprio navigate.py que resolve, ja sabendo qual dos
    # dois esta procurando.
    #
    # So um par vira fixture aqui, nao dois: um segundo par (Advanced +
    # Boot) capturado na mesma sessao (2026-08-24) mostrou que esse caso
    # pode estar bem na fronteira de deteccao -- a mesma imagem, salva em
    # JPG e relida, mudou de "abstem" para "decide sozinho" so por causa
    # da compressao com perda. Nao e um caso estavel para travar como
    # fixture; ver a nota em `study_sidebar_stability.py` sobre por que
    # frames agora sao salvos em PNG.
    reading = legacy_reading_for("positivo_sidebar_pattern3_advanced-security")
    marked = screen.legacy_cursor(reading)
    check("padrao 3: selection.py sozinho abstem", marked, None)

    fallback = navigate._sidebar_colour_fallback(reading, "Security")
    check_that("padrao 3: fallback acha o alvo certo",
               fallback is not None
               and screen.normalize(fallback["text"]) == "security",
               f"achou: {fallback['text'] if fallback else None}")

    # O outro item escuro (a pagina aberta) nao pode ser o resultado --
    # o fallback so deve responder quando esta procurando `target`.
    other = navigate._sidebar_colour_fallback(reading, "Nao Existe Na Tela")
    check("padrao 3: fallback nao inventa alvo quando nao encontra o seu",
          other, None)


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
    test_goto_screen(menu)
    test_all_fields_scroll_merges_pages()
    test_ask_sends_a_system_prompt(menu, readings)
    test_verbatim_accepts_pt_br_toggle_synonyms()
    test_assistant_catches_a_hallucinated_value(menu, readings)
    test_menu_walk(menu)
    test_walk_survives_stuck_cursor(menu)
    test_setup_icon_anchor()
    test_sidebar_legacy_cursor()
    test_safety_guards(menu)

    print()
    if _failures:
        print(f"{len(_failures)} falha(s): {', '.join(_failures)}")
        return 1
    print("tudo passou")
    return 0


if __name__ == "__main__":
    sys.exit(main())
