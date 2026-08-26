"""Two follow-up checks for the mouse-click prototype, run back to back in
one continuous session (separate debug invocations kept re-triggering the
pointer's idle-hide behaviour between them):

1. Does clicking a dropdown open it, and can it be closed again WITHOUT
   changing the stored value (single click to open, no drag/second click
   needed to commit)?
2. Does clicking near the sidebar's "Setup" back-arrow risk opening
   'Discard Changes and Exit' the way ESC does on the keyboard path?

Never confirms a value change and never answers a dialog with anything
but Cancel/Esc.
"""
import cv2
import time

from biostools.session import BiosSession
from biostools.navigate import looks_like_dialog
from biostools.screen import field_value, legacy_cursor
from study_mouse_navigation import MouseTracker, click_text, fresh_frame

def calibrate_with_retries(session, attempts=4):
    """`calibrate()` has failed intermittently live -- the pointer's own
    idle-hide behaviour racing a slow-ish probe read. Each attempt is
    cheap (a few seconds) and independent, so retrying in-process is far
    cheaper than diagnosing why any ONE attempt failed, and safe: a
    failed probe only ever sends arrow-equivalent mouse moves, never a
    click.
    """
    last_error = None
    for attempt in range(1, attempts + 1):
        tracker = MouseTracker(session)
        try:
            tracker.calibrate()
            return tracker
        except RuntimeError as exc:
            last_error = exc
            print(f"  calibracao tentativa {attempt} falhou: {exc}")
    raise RuntimeError(f"calibracao falhou {attempts}x seguidas: {last_error}")


if __name__ == "__main__":
 with BiosSession(serial_port="COM3") as s:
    tracker = calibrate_with_retries(s)
    print(f"calibrado: pos=({tracker.x:.0f},{tracker.y:.0f})")

    # -- 1. dropdown -----------------------------------------------------
    r = s.read_stable()
    before_value = field_value(r.full, "Wake on PCI/PCIE")
    print(f"\n[dropdown] valor antes: {before_value.value if before_value else None}")

    ok = click_text(s, tracker, "Enabled")
    print(f"[dropdown] clicou pra abrir: {ok}")
    r2 = s.read_cursor()
    cv2.imwrite("captures/handshake/pc2_dropdown_estado.png", r2["frame"])
    if looks_like_dialog(r2):
        print("[dropdown] ATENCAO: parece dialogo, nao um dropdown -- fechando com esc")
        s.press("esc")
    else:
        opened_lines = [l["text"] for b in r2["blocks"] for l in b["lines"]]
        print(f"[dropdown] texto na tela apos clique: {opened_lines[:12]}")
        # Fecha sem mudar nada: Esc fecha um dropdown sem confirmar selecao
        # nesta familia de BIOS AMI (padrao comum -- nao verificado aqui
        # antes, primeira vez testando).
        s.press("esc")
        s._dirty = True

    r3 = s.read_stable()
    after_value = field_value(r3.full, "Wake on PCI/PCIE")
    print(f"[dropdown] valor depois: {after_value.value if after_value else None}")
    print(f"[dropdown] mudou? {before_value.value != after_value.value if before_value and after_value else 'desconhecido'}")

    # -- 2. clique perto da borda / icone Setup --------------------------
    print("\n[borda] recalibrando antes do teste de borda...")
    tracker2 = calibrate_with_retries(s)

    # O icone fica por volta de x=18-56, y=78-115 em 1280x720 (mesma caixa
    # usada por navigate.setup_icon_focused no caminho de teclado).
    target_x, target_y = 40, 95
    print(f"[borda] mirando perto do icone Setup ({target_x},{target_y})...")
    converged = tracker2.move_to(target_x, target_y, tolerance=15)
    print(f"[borda] convergiu? {converged}  pos=({tracker2.x:.0f},{tracker2.y:.0f})")

    if converged:
        before_click = s.read_cursor()
        cv2.imwrite("captures/handshake/pc2_antes_clique_borda.png", before_click["frame"])
        s.actuator.mouse_click("left")
        s._dirty = True
        after_click = s.read_cursor()
        cv2.imwrite("captures/handshake/pc2_apos_clique_borda.png", after_click["frame"])
        if looks_like_dialog(after_click):
            print("[borda] ABRIU DIALOGO -- mesmo risco do teclado. Fechando com esc.")
            s.press("esc")
            confirm = s.read_cursor()
            print(f"[borda] dialogo fechado? {not looks_like_dialog(confirm)}")
        else:
            txt = [l["text"] for b in after_click["blocks"] for l in b["lines"]]
            print(f"[borda] sem dialogo. texto apos clique: {txt[:8]}")
    else:
        print("[borda] nao convergiu perto o suficiente -- nao cliquei")

    print("\n--- estado final ---")
    final = s.read_cursor()
    print("dialogo aberto?", looks_like_dialog(final))
