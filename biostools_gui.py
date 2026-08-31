"""Mini app: ask the BIOS a question in plain text, get a verified answer.

    py -3.13 biostools_gui.py

One text field is the whole point -- an operator types a question, the
LLM (`biostools.assistant`) picks and runs the right tool(s) against the
real machine, and the answer comes back verified (see assistant.py's
docstring for what "verified" means and why it matters). Everything else
in the window exists to make that one field trustworthy:

* three status lights (IA / Camera / Teclado virtual) say which of the
  three real subsystems a question depends on are actually up, instead
  of a question silently failing with no clue which piece is missing;
* a tools panel lists every registered tool by name and by the question
  it answers, and lets an operator run one directly -- useful for
  testing a single tool, or answering something the LLM router declined.

One `BiosSession` is opened on "Conectar" and reused for every question
and every manual tool click after that -- see `biostools/session.py`'s
own docstring for why paying the OCR-model load per call would make this
unusable.

**Threading, and why it is simple here.** `gui.py` (the OCR capture app)
needed a whole subprocess for OCR because PaddleOCR holds the GIL for
seconds at a time on this CPU. `biostools` reads are the fast path
instead (rapidocr-openvino, ~0.5-2s per read, measured in
`biostools/session.py`'s own history) and an LLM call is I/O-bound, not
CPU-bound, so it does not hold the GIL either. One background `Thread`
per action is enough; a `queue.Queue` carries results back to Tk's main
thread, which is the only thread allowed to touch widgets.
"""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import scrolledtext, ttk

from actuator import CableNotResponding, list_serial_ports
from capture import list_camera_devices
from extract import DEFAULT_HOST, DEFAULT_PORT
from ocr import DEFAULT_ENGINE, ENGINE_CHOICES

from biostools import BiosSession, list_tools, run_tool
from biostools.assistant import ASSISTANT_MODEL
from biostools.session import ActuatorUnavailable, CameraUnavailable

AI_CHECK_TIMEOUT = 2.0

# How often `_poll_tunnel` checks whether the ssh child is still alive,
# and how long to wait, from launch, before treating "still alive" as
# "the tunnel is up" -- has to be generous enough for a human to notice a
# password prompt in the console window that popped up and type into it,
# not just long enough for the network handshake itself.
TUNNEL_POLL_INTERVAL_MS = 1500
TUNNEL_GRACE_PERIOD_S = 8


class _Indicator:
    """One status light: a coloured dot plus a short label.

    Three independent states, not a boolean -- "desconhecido" (never
    checked, grey) has to be visually distinct from "desconectado" (
    checked, and it is down, red). Collapsing them would make "I haven't
    looked yet" look identical to "it's broken", which is worse than not
    showing a light at all.
    """
    COLORS = {"unknown": "#888888", "ok": "#2e8b2e", "down": "#c0392b"}
    LABELS = {"unknown": "desconhecido", "ok": "conectado", "down": "desconectado"}

    def __init__(self, parent, name):
        self.name = name
        self.frame = ttk.Frame(parent)
        self.dot = tk.Canvas(self.frame, width=14, height=14,
                             highlightthickness=0)
        self.dot.pack(side=tk.LEFT, padx=(0, 4))
        self._oval = self.dot.create_oval(2, 2, 12, 12, fill=self.COLORS["unknown"],
                                          outline="")
        self.text = tk.StringVar(value=f"{name}: {self.LABELS['unknown']}")
        ttk.Label(self.frame, textvariable=self.text).pack(side=tk.LEFT)

    def set(self, state, detail=None):
        self.dot.itemconfig(self._oval, fill=self.COLORS[state])
        label = self.LABELS[state] if detail is None else detail
        self.text.set(f"{self.name}: {label}")


class BiosAssistantApp:
    def __init__(self, root):
        self.root = root
        self.root.title("BIOS Assistant")
        self.root.geometry("760x620")

        self.session = None
        self.busy = False
        self.queue = queue.Queue()
        self.tools_window = None
        self.tunnel_process = None

        self._build_ui()
        self._refresh_devices()
        self.root.after(100, self._poll_queue)

    # -- layout ------------------------------------------------------------

    def _build_ui(self):
        pad = dict(padx=8, pady=4)

        conn = ttk.LabelFrame(self.root, text="Conexao")
        conn.pack(fill=tk.X, **pad)

        row1 = ttk.Frame(conn)
        row1.pack(fill=tk.X, padx=6, pady=(6, 2))
        ttk.Label(row1, text="Camera:").pack(side=tk.LEFT)
        self.camera_var = tk.StringVar(value="0")
        self.camera_combo = ttk.Combobox(row1, textvariable=self.camera_var, width=28)
        self.camera_combo.pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(row1, text="Cabo (COM):").pack(side=tk.LEFT)
        self.serial_var = tk.StringVar(value="")
        self.serial_combo = ttk.Combobox(row1, textvariable=self.serial_var, width=22)
        self.serial_combo.pack(side=tk.LEFT, padx=(4, 8))
        ttk.Button(row1, text="Atualizar", command=self._refresh_devices).pack(side=tk.LEFT)

        row2 = ttk.Frame(conn)
        row2.pack(fill=tk.X, padx=6, pady=(2, 2))
        ttk.Label(row2, text="Motor OCR:").pack(side=tk.LEFT)
        self.engine_var = tk.StringVar(value=DEFAULT_ENGINE)
        ttk.Combobox(row2, textvariable=self.engine_var, values=ENGINE_CHOICES,
                    width=20, state="readonly").pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(row2, text="IA host:").pack(side=tk.LEFT)
        self.llm_host_var = tk.StringVar(value=DEFAULT_HOST)
        ttk.Entry(row2, textvariable=self.llm_host_var, width=14).pack(side=tk.LEFT, padx=(4, 4))
        ttk.Label(row2, text="porta:").pack(side=tk.LEFT)
        self.llm_port_var = tk.StringVar(value=str(DEFAULT_PORT))
        ttk.Entry(row2, textvariable=self.llm_port_var, width=7).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(row2, text="modelo:").pack(side=tk.LEFT)
        # The assistant's own model, not the OCR-extraction one -- this
        # field only ever feeds assistant.ask(). See assistant.py for
        # the measurement behind the choice.
        self.llm_model_var = tk.StringVar(value=ASSISTANT_MODEL)
        ttk.Entry(row2, textvariable=self.llm_model_var, width=18).pack(side=tk.LEFT, padx=(4, 0))

        # Optional: the machine running the LLM binds its API to loopback
        # only (see docs/reference/MANUAL_APRESENTACAO_BIOS.md, "Máquina de
        # IA") -- when it hasn't been reconfigured to listen on the LAN, an
        # SSH tunnel is what makes "IA host: 127.0.0.1" above actually
        # reach it. Independent of "Conectar": the tunnel is a network
        # path to the IA, not part of the camera/cable session, so it has
        # its own open/close pair rather than being folded into connect.
        row_tunnel = ttk.Frame(conn)
        row_tunnel.pack(fill=tk.X, padx=6, pady=(2, 2))
        ttk.Label(row_tunnel, text="Tunel SSH ate a IA (opcional):").pack(side=tk.LEFT)
        self.ssh_target_var = tk.StringVar()
        ttk.Entry(row_tunnel, textvariable=self.ssh_target_var, width=22).pack(
            side=tk.LEFT, padx=(4, 8))
        self.tunnel_button = ttk.Button(row_tunnel, text="Abrir tunel",
                                        command=self._toggle_tunnel)
        self.tunnel_button.pack(side=tk.LEFT)
        self.tunnel_status_var = tk.StringVar(value="sem tunel")
        ttk.Label(row_tunnel, textvariable=self.tunnel_status_var).pack(
            side=tk.LEFT, padx=(8, 0))

        row_nav = ttk.Frame(conn)
        row_nav.pack(fill=tk.X, padx=6, pady=(2, 2))
        ttk.Label(row_nav, text="Navegacao:").pack(side=tk.LEFT)
        self.nav_mode_var = tk.StringVar(value="keyboard")
        for value, label in (("keyboard", "Teclado"), ("mouse", "Mouse"),
                             ("auto", "Auto")):
            ttk.Radiobutton(row_nav, text=label, value=value,
                            variable=self.nav_mode_var).pack(side=tk.LEFT, padx=(4, 0))

        row3 = ttk.Frame(conn)
        row3.pack(fill=tk.X, padx=6, pady=(2, 6))
        self.connect_button = ttk.Button(row3, text="Conectar", command=self._connect)
        self.connect_button.pack(side=tk.LEFT)
        self.disconnect_button = ttk.Button(row3, text="Desconectar",
                                            command=self._disconnect, state=tk.DISABLED)
        self.disconnect_button.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(row3, text="Ver tools", command=self._open_tools_window).pack(
            side=tk.LEFT, padx=(6, 0))

        status = ttk.Frame(self.root)
        status.pack(fill=tk.X, padx=8, pady=(0, 4))
        self.ind_ai = _Indicator(status, "IA")
        self.ind_ai.frame.pack(side=tk.LEFT, padx=(0, 16))
        self.ind_camera = _Indicator(status, "Camera")
        self.ind_camera.frame.pack(side=tk.LEFT, padx=(0, 16))
        self.ind_actuator = _Indicator(status, "Teclado virtual")
        self.ind_actuator.frame.pack(side=tk.LEFT)

        ask = ttk.LabelFrame(self.root, text="Pergunta")
        ask.pack(fill=tk.X, padx=8, pady=4)
        self.question_var = tk.StringVar()
        self.question_entry = ttk.Entry(ask, textvariable=self.question_var)
        self.question_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6, pady=6)
        self.question_entry.bind("<Return>", lambda e: self._ask())
        self.ask_button = ttk.Button(ask, text="Perguntar", command=self._ask)
        self.ask_button.pack(side=tk.LEFT, padx=(0, 6), pady=6)

        answer = ttk.LabelFrame(self.root, text="Resposta")
        answer.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))
        self.answer_text = scrolledtext.ScrolledText(answer, wrap=tk.WORD, state=tk.DISABLED)
        self.answer_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self.status_var = tk.StringVar(value="desconectado")
        ttk.Label(self.root, textvariable=self.status_var, anchor=tk.W).pack(
            fill=tk.X, padx=8, pady=(0, 6))

    # -- device lists --------------------------------------------------

    def _refresh_devices(self):
        try:
            cams = list_camera_devices()
            self.camera_combo["values"] = cams or ["0"]
        except Exception:
            self.camera_combo["values"] = ["0"]
        ports = list_serial_ports()
        self.serial_combo["values"] = [f"{dev}: {desc}" for dev, desc in ports]

    # -- background-thread plumbing -------------------------------------

    def _run_in_background(self, fn, on_done):
        """Run `fn()` off the Tk thread; `on_done(result, error)` runs on
        it, via the queue `_poll_queue` drains. Disables the inputs a
        question/tool-run/connect would race with while busy, since this
        app deliberately runs one hardware operation at a time.
        """
        if self.busy:
            return
        self.busy = True
        self._set_busy_widgets(tk.DISABLED)

        def worker():
            try:
                result = fn()
                self.queue.put((on_done, result, None))
            except Exception as exc:  # noqa: BLE001 -- surfaced to the UI, not swallowed
                self.queue.put((on_done, None, exc))

        threading.Thread(target=worker, daemon=True).start()

    def _set_busy_widgets(self, state):
        self.ask_button.config(state=state)
        self.connect_button.config(state=state)
        self.disconnect_button.config(state=state)
        for child in self._tool_buttons():
            child.config(state=state)

    def _tool_buttons(self):
        if self.tools_window is None or not self.tools_window.winfo_exists():
            return []
        return [w for w in self.tools_window.winfo_children()
               if isinstance(w, ttk.Button)]

    def _poll_queue(self):
        try:
            while True:
                on_done, result, error = self.queue.get_nowait()
                self.busy = False
                self._set_busy_widgets(tk.NORMAL)
                if self.session is None:
                    self.connect_button.config(state=tk.NORMAL)
                    self.disconnect_button.config(state=tk.DISABLED)
                else:
                    self.connect_button.config(state=tk.DISABLED)
                    self.disconnect_button.config(state=tk.NORMAL)
                on_done(result, error)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    # -- answer panel -----------------------------------------------------

    def _show_answer(self, text):
        self.answer_text.config(state=tk.NORMAL)
        self.answer_text.delete("1.0", tk.END)
        self.answer_text.insert(tk.END, text)
        self.answer_text.config(state=tk.DISABLED)

    # -- connect / disconnect ----------------------------------------------

    def _connect(self):
        camera = self.camera_var.get().split(":")[0].strip()
        serial = self.serial_var.get().split(":")[0].strip() or None
        engine = self.engine_var.get()
        self.status_var.set("conectando...")

        def work():
            return BiosSession(camera_source=camera, serial_port=serial, engine=engine)

        def done(session, error):
            if error is not None:
                self.status_var.set(f"falha ao conectar: {error}")
                self.ind_camera.set("down", str(error)[:40])
                return
            self.session = session
            self.status_var.set("conectado")
            self.ind_camera.set("ok")
            self.ind_actuator.set("ok" if session.actuator is not None else "down",
                                  None if session.actuator is not None
                                  else "sem cabo (--serial-port)")
            self._check_ai()

        self._run_in_background(work, done)

    def _disconnect(self):
        # Closing the actuator's serial port while a background thread is
        # mid-keypress is not just untidy -- it can drop the BREAK half of
        # a make/break pair, and the KM232 repeats a key that never got
        # its break (see actuator.py's own docstring on this). Caught for
        # real 2026-08-24: disconnecting while a tool was still navigating
        # left a confirmation dialog open on the real machine, most likely
        # from exactly this. Refusing here is cheap; a stuck key on a live
        # machine is not.
        if self.busy:
            self.status_var.set("aguarde a operacao atual terminar antes de desconectar")
            return
        if self.session is not None:
            self.session.close()
            self.session = None
        self.status_var.set("desconectado")
        self.ind_camera.set("unknown")
        self.ind_actuator.set("unknown")
        self.connect_button.config(state=tk.NORMAL)
        self.disconnect_button.config(state=tk.DISABLED)

    # -- SSH tunnel to the IA machine ---------------------------------------

    def _toggle_tunnel(self):
        if self.tunnel_process is None:
            self._open_tunnel()
        else:
            self._close_tunnel()

    def _open_tunnel(self):
        target = self.ssh_target_var.get().strip()
        if not target:
            self.tunnel_status_var.set("informe usuario@host antes de abrir")
            return
        try:
            port = int(self.llm_port_var.get())
        except ValueError:
            self.tunnel_status_var.set(f"porta de IA invalida: {self.llm_port_var.get()!r}")
            return

        # -N: only forward, never run a remote command. No BatchMode, and
        # (on Windows) CREATE_NEW_CONSOLE instead of CREATE_NO_WINDOW: ssh
        # gets a REAL, separate console, so a password or host-key
        # confirmation prompt shows up exactly as it would in a terminal
        # the operator opened by hand -- and the operator types straight
        # into THAT window. This process only ever watches whether the
        # child is still alive (`proc.poll()`); it never reads, stores,
        # or relays a single byte of what gets typed there. That is the
        # line: automating the *launch* of an interactive prompt is
        # convenience, capturing or entering the *credential* on someone's
        # behalf is the thing this project never does, in the GUI or
        # anywhere else. -o StrictHostKeyChecking=accept-new still saves
        # one extra prompt for a first-time host (later connections are
        # still verified against known_hosts as usual).
        cmd = [
            "ssh", "-N",
            "-L", f"{port}:127.0.0.1:{port}",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=15",
            target,
        ]
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

        self.tunnel_status_var.set("abrindo -- digite a senha na janela que abriu, se pedido")
        try:
            self.tunnel_process = subprocess.Popen(cmd, **kwargs)
        except FileNotFoundError:
            self.tunnel_process = None
            self.tunnel_status_var.set(
                "'ssh' nao encontrado -- instale o OpenSSH Client do Windows "
                "(Configuracoes > Aplicativos > Recursos opcionais)")
            return

        self._tunnel_confirmed = False
        self._tunnel_opened_at = time.monotonic()
        self.tunnel_button.config(text="Fechar tunel")
        self.root.after(TUNNEL_POLL_INTERVAL_MS, self._poll_tunnel)

    def _poll_tunnel(self):
        """Runs every `TUNNEL_POLL_INTERVAL_MS` for as long as a tunnel
        process is tracked -- not a one-shot check. Two jobs: notice a
        tunnel that never came up (wrong password typed, host unreachable,
        port already in use -- ssh exits, often within seconds) without
        guessing why from here (that detail is in the console window
        itself, not captured by this process), and notice a tunnel that
        was up and later dropped (window closed, network blip) instead of
        the GUI silently believing a dead tunnel is still there.
        """
        proc = self.tunnel_process
        if proc is None:
            return  # closed via the button meanwhile; nothing to poll
        code = proc.poll()
        if code is not None:
            self.tunnel_process = None
            self.tunnel_button.config(text="Abrir tunel")
            self.tunnel_status_var.set(
                f"tunel fechou (codigo {code}) -- veja a janela do terminal "
                f"que abriu para o motivo")
            return
        elapsed = time.monotonic() - self._tunnel_opened_at
        if not self._tunnel_confirmed and elapsed >= TUNNEL_GRACE_PERIOD_S:
            # Enough time for a human to notice the prompt and type a
            # password; still alive past this point is the signal it is
            # up. Confirmed for real by handing off to `_check_ai`, the
            # same reachability probe "Conectar" already uses, rather than
            # trusting "the process didn't exit" on its own.
            self._tunnel_confirmed = True
            self.tunnel_status_var.set(f"tunel ativo (pid {proc.pid})")
            self._check_ai()
        self.root.after(TUNNEL_POLL_INTERVAL_MS, self._poll_tunnel)

    def _close_tunnel(self):
        if self.tunnel_process is None:
            return
        # terminate() sends SIGTERM (Windows: TerminateProcess) -- there is
        # no in-flight hardware state to protect here, unlike
        # `_disconnect`'s refusal while busy; a port forward has nothing
        # equivalent to a stuck key mid-press.
        self.tunnel_process.terminate()
        try:
            self.tunnel_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.tunnel_process.kill()
        self.tunnel_process = None
        self.tunnel_button.config(text="Abrir tunel")
        self.tunnel_status_var.set("sem tunel")

    def _check_ai(self):
        """A lightweight reachability probe, separate from asking a real
        question -- so the light can turn red/green without spending a
        tool call or waiting on a full LLM round trip.
        """
        import requests

        host, port = self.llm_host_var.get(), self.llm_port_var.get()

        def work():
            resp = requests.get(f"http://{host}:{port}/api/v1/models",
                                timeout=AI_CHECK_TIMEOUT)
            resp.raise_for_status()
            return True

        def done(_result, error):
            self.ind_ai.set("down" if error else "ok",
                            str(error)[:40] if error else None)

        self._run_in_background(work, done)

    # -- asking a question --------------------------------------------------

    def _ask(self):
        question = self.question_var.get().strip()
        if not question:
            return
        if self.session is None:
            self._show_answer("Conecte a camera (e o cabo, se a pergunta precisar "
                              "mover o cursor) antes de perguntar.")
            return

        from biostools import assistant

        host, model = self.llm_host_var.get(), self.llm_model_var.get()
        try:
            port = int(self.llm_port_var.get())
        except ValueError:
            self._show_answer(f"porta de IA invalida: {self.llm_port_var.get()!r}")
            return

        self.status_var.set(f"perguntando: {question!r} ...")
        self._show_answer("(pensando...)")

        def work():
            return assistant.ask(question, self.session, host=host, port=port,
                                 model=model, nav_mode=self.nav_mode_var.get())

        def done(result, error):
            if error is not None:
                self._show_answer(f"Erro: {error}")
                self.status_var.set("erro")
                if isinstance(error, (CameraUnavailable, ActuatorUnavailable,
                                      CableNotResponding)):
                    self.ind_camera.set("down") if isinstance(
                        error, CameraUnavailable) else None
                return
            self.ind_ai.set("down" if result.error else "ok",
                            result.error[:40] if result.error else None)
            if result.error and not result.calls:
                # The endpoint itself is unreachable -- nothing was tried,
                # so `result.answer` is empty and showing it blank would
                # look like the app hung rather than told anything.
                self._show_answer(f"A IA nao respondeu: {result.error}\n\n"
                                  "Confira o host/porta/tunel de IA acima, ou "
                                  "abra 'Ver tools' para rodar uma tool direto, "
                                  "sem depender da IA.")
                self.status_var.set("IA inacessivel")
                return
            lines = [result.answer]
            if result.calls:
                lines.append("")
                lines.append("tools usadas: " + ", ".join(
                    f"{c.tool}{'' if c.result and c.result.ok else ' (falhou)'}"
                    for c in result.calls))
            self._show_answer("\n".join(lines))
            self.status_var.set("pronto")

        self._run_in_background(work, done)

    # -- tools panel ---------------------------------------------------

    def _open_tools_window(self):
        if self.tools_window is not None and self.tools_window.winfo_exists():
            self.tools_window.lift()
            return

        win = tk.Toplevel(self.root)
        win.title("Tools disponiveis")
        win.geometry("420x360")
        self.tools_window = win

        canvas = tk.Canvas(win, highlightthickness=0)
        scrollbar = ttk.Scrollbar(win, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for name, question in list_tools().items():
            row = ttk.Frame(inner)
            row.pack(fill=tk.X, padx=6, pady=3)
            btn = ttk.Button(row, text=name.replace("_", "-"), width=18,
                             command=lambda n=name: self._run_tool_clicked(n))
            btn.pack(side=tk.LEFT)
            ttk.Label(row, text=question, wraplength=220).pack(side=tk.LEFT, padx=(6, 0))

    def _run_tool_clicked(self, name):
        if self.session is None:
            self._show_answer("Conecte antes de rodar uma tool.")
            return
        self.status_var.set(f"rodando tool {name!r} ...")
        self._show_answer(f"(rodando {name}...)")

        def work():
            return run_tool(name, self.session, mode=self.nav_mode_var.get())

        def done(result, error):
            if error is not None:
                self._show_answer(f"{name}: erro -- {error}")
                self.status_var.set("erro")
                return
            self._show_answer(f"[{name}]\n\n{result.as_text()}")
            self.status_var.set("pronto")

        self._run_in_background(work, done)

    # -- lifecycle -----------------------------------------------------

    def on_close(self):
        # Same reasoning as `_disconnect`: closing the window closes the
        # session, and doing that mid-keypress risks a stuck key on the
        # real machine. Refuse and let the status bar say why, rather than
        # silently ignoring the click -- an operator clicking X twice with
        # no feedback would just conclude the app is frozen.
        if self.busy:
            self.status_var.set("operacao em andamento -- aguarde antes de fechar")
            return
        if self.session is not None:
            self.session.close()
        if self.tunnel_process is not None:
            self._close_tunnel()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = BiosAssistantApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
