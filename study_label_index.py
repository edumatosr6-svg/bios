"""Colher os rótulos desta máquina: primeiro crus (F0), depois indexados (F3).

Two modes, and the order between them is not a preference -- it is the
only order that works:

    py -3.13 study_label_index.py --harvest --serial-port COM3
        P3a. Walks every top-level screen except `save_and_exit`, scrolls
        each page to the end, and dumps ALL content text into
        `data/raw_labels/<tela>.json`. Matches nothing against
        `labels.py`, enters no submenu. This is what can be done BEFORE
        any submenu has a declared spelling -- which is the whole reason
        it exists.

    *** then a person edits biostools/labels.py by hand ***
        Reads the dumps, decides which raw line is which concept, and
        marks `# CONFIRMADO -- Positivo, <data>` plus
        `provenance: "CONFIRMADO"` in `SUBMENUS` for what was really
        seen. No mode of this script does that step, deliberately -- see
        `biostools/harvest.py`.

    py -3.13 study_label_index.py --serial-port COM3
        P4. The tour: every top-level screen except `save_and_exit`, plus
        every CONFIRMADO submenu, each page scrolled to the end, written
        to `data/label_index.json` and validated before it is written.

Running the tour before the harvest is not an error and does not fail: it
produces an index with no submenu pages, and every submenu listed in
`skipped` with `provenance=palpite` or `grafia nao declarada`. That is the
honest state of a machine nobody has bootstrapped yet.

There is also an offline path:

    py -3.13 study_label_index.py --from-captures captures/menu_tour_.../

which replays frames already photographed off the target machine instead
of driving it live. Same code, same output; it needs no cable and no
camera, and the material is just as real -- it was read off this machine,
which is the only property `labels.py`'s discipline actually demands. It
is how the first committed artefacts of this slug were produced, and how
they can be regenerated without booking bench time.

`save_and_exit` is never visited by any of them. Every key sent is in
`registry.SAFE_KEYS`.
"""
import argparse
import json
import os
import sys

from biostools import harvest, index
from biostools.page import MAX_SCREENS
from biostools.session import BiosSession
from ocr import DEFAULT_ENGINE, ENGINE_CHOICES


class CaptureSession:
    """A session backed by saved frames instead of a live machine.

    Serves one still page per top-level screen: `press` is accepted and
    recorded (so the SAFE_KEYS assertions still mean something) but moves
    nothing, which makes every page read as a single screenful that ends
    immediately -- true of these captures, which are one frame each.

    Not a test double: this drives the real perception pipeline over real
    photographs of the target machine. What it cannot do is scroll, so an
    index built through it covers the first screenful of each page and
    says so.
    """

    def __init__(self, frames, engine=DEFAULT_ENGINE):
        from ocr import create_ocr_engine
        from perception import perceive

        self.pressed = []
        self._engine = create_ocr_engine(engine)
        self._perceive = perceive
        self._frames = frames          # {canonical screen: image}
        self._contracts = {}
        self.current = next(iter(frames))
        self.actuator = None

    def press(self, key):
        self.pressed.append(key)

    def _contract(self, screen):
        if screen not in self._contracts:
            self._contracts[screen] = self._perceive(
                frames=[self._frames[screen]], view="both").contract
        return self._contracts[screen]

    def read_stable(self, timeout=None):
        from biostools.session import Reading

        contract = self._contract(self.current)
        return Reading(full=contract["full"], digest=contract["digest"],
                       frame=self._frames[self.current], captured_at="capture")

    def read_cursor(self, timeout=None):
        from selection import annotate_selection

        frame = self._frames[self.current]
        result = self._engine.read(frame)
        result["screen_bg_color"] = annotate_selection(frame, result["blocks"])
        result["frame"] = frame
        return result

    def enter(self, screen):
        """Switch to a captured page. Used by the offline navigation stub
        below, which stands in for `enter_main_menu_screen` -- these
        frames were captured one per page, so 'navigating' to one is
        selecting its frame."""
        if screen not in self._frames:
            return False
        self.current = screen
        return True


def _offline_navigation(session):
    """Point `enter_main_menu_screen` at the captured frames.

    Patched rather than parameterised: navigation is one shared building
    block on purpose (see its docstring), and threading a "which frames"
    argument through every caller to serve one offline script would be a
    worse trade than one clearly-scoped patch here in study code.
    """
    from biostools import harvest as harvest_mod
    from biostools import index as index_mod
    from biostools import submenu as submenu_mod
    from biostools.navigate import ARRIVED, BLIND, NavigationResult

    def stub(sess, screen, activate_key="enter", max_steps=20,
             mode="keyboard", click_settle_delay=0.0):
        if sess.enter(screen):
            return (NavigationResult(ok=True, reason=ARRIVED, steps=0,
                                     reading=sess.read_cursor()), None)
        return (NavigationResult(
            ok=False, reason=BLIND, steps=0,
            detail=f"nao ha frame capturado para {screen!r}"), None)

    for module in (harvest_mod, index_mod, submenu_mod):
        module.enter_main_menu_screen = stub


def load_capture_frames(directory):
    """`{canonical screen: image}` from a `study_menu_tour.py` output dir.

    The tour's own `pages.json` says which page index is which screen, so
    the mapping is read from the capture rather than assumed from file
    order.
    """
    import cv2

    with open(os.path.join(directory, "pages.json"), encoding="utf-8") as f:
        meta = json.load(f)

    by_page = {}
    for step in meta.get("timeline", ()):
        by_page.setdefault(step["page"], step["menu"])

    frames = {}
    for page in meta.get("pages", ()):
        screen = by_page.get(page["index"])
        if not screen or screen == index.FORBIDDEN_SCREEN:
            continue
        path = os.path.join(directory, f"page{page['index']:02d}.png")
        image = cv2.imread(path)
        if image is None:
            sys.exit(f"frame ausente: {path}")
        frames[screen] = image
    if not frames:
        sys.exit(f"nenhum frame utilizavel em {directory}")
    return frames


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--harvest", action="store_true",
                        help="Modo F0: despeja o texto cru de cada tela em "
                             "data/raw_labels/, sem casar contra labels.py")
    parser.add_argument("--from-captures",
                        help="Rodar offline sobre um diretorio de captura do "
                             "study_menu_tour.py, sem camera nem cabo")
    parser.add_argument("--camera-source", default="0")
    parser.add_argument("--engine", choices=ENGINE_CHOICES, default=DEFAULT_ENGINE)
    parser.add_argument("--resolution", default="1280x720")
    parser.add_argument("--serial-port")
    parser.add_argument("--max-screens", type=int, default=MAX_SCREENS)
    parser.add_argument("--bios-version", default=index.TARGET_BIOS_VERSION)
    parser.add_argument("--bios-model", default=index.TARGET_MODEL)
    parser.add_argument("--source",
                        help="Como as telas foram lidas, gravado no cabecalho "
                             "do indice (ex.: o diretorio de captura)")
    parser.add_argument("--captured-at",
                        help="Timestamp ISO a gravar no cabecalho do indice; "
                             "use a data da captura ao rodar --from-captures")
    return parser.parse_args()


def run(session, args):
    if args.harvest:
        print("colhendo texto cru (F0 / P3a)...")
        result = harvest.harvest(session, max_screens=args.max_screens,
                                 on_event=lambda m: print("  " + m))
        print(f"\n{len(result['written'])} dump(s) em {harvest.RAW_LABELS_DIR}/")
        for item in result["skipped"]:
            print(f"  pulada: {item['screen']} -- {item['reason']}")
        print("\nPROXIMO PASSO, HUMANO: leia os dumps, identifique as linhas "
              "de submenu e edite biostools/labels.py (SCREENS + SUBMENUS) "
              "marcando CONFIRMADO so no que voce viu. Nenhum modo deste "
              "script faz isso -- ver biostools/harvest.py.")
        return 0

    print("mapeando a maquina inteira (F3 / P4)...")
    report = index.tour(session, max_screens=args.max_screens,
                        bios_model=args.bios_model,
                        bios_version=args.bios_version,
                        captured_at=args.captured_at,
                        source=args.source,
                        on_event=lambda m: print("  " + m))
    try:
        path = index.save(report)
    except index.IndexInvalid as e:
        print(f"\nindice NAO gravado -- ele nao passa no proprio validador: {e}")
        return 1

    print(f"\n{len(report['entries'])} rotulos em {len(report['pages'])} "
          f"pagina(s) -> {path}")
    for item in report["skipped"]:
        where = item["screen"] + (f"/{item['submenu']}" if item["submenu"] else "")
        print(f"  pulada: {where} -- {item['reason']}")
    print("\nCOMITE o arquivo. O caminho generico de resposta depende dele "
          "(ver docs/specs/p-specs/fixture-de-teste-nunca-versionada.md).")
    return 0


def main():
    args = parse_args()

    if args.from_captures:
        frames = load_capture_frames(args.from_captures)
        session = CaptureSession(frames, engine=args.engine)
        _offline_navigation(session)
        args.source = args.source or (
            f"replay offline de {args.from_captures} -- frames reais da "
            f"maquina alvo, uma tela por pagina, sem rolagem: cada pagina "
            f"cobre apenas o primeiro screenful")
        print(f"modo offline: {len(frames)} pagina(s) capturada(s) em "
              f"{args.from_captures}")
        status = run(session, args)
        unsafe = set(session.pressed) - set(__import__(
            "biostools.registry", fromlist=["SAFE_KEYS"]).SAFE_KEYS)
        if unsafe:
            print(f"ALERTA: teclas fora de SAFE_KEYS: {sorted(unsafe)}")
        return status

    if not args.serial_port:
        sys.exit("este modo dirige a maquina: passe --serial-port (ex.: COM3), "
                 "ou use --from-captures para rodar offline")

    resolution = tuple(int(v) for v in args.resolution.lower().split("x"))
    with BiosSession(camera_source=args.camera_source, engine=args.engine,
                     resolution=resolution,
                     serial_port=args.serial_port) as session:
        return run(session, args)


if __name__ == "__main__":
    sys.exit(main())
