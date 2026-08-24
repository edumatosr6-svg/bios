"""Where is the keyboard focus, and does `left` FORCE the sidebar or TOGGLE?

The open question from `docs/specs/p-specs/deteccao-cursor-barra-lateral-
instavel-entre-frames.md`: a live sequence of left/down/left/down produced
`Main -> Main -> None -> None -> Main`, which no simple monotonic cursor
movement explains. One hypothesis (recorded, never isolated) is that
`left` *toggles* focus between sidebar and content rather than always
handing it to the sidebar -- which would make every navigation built on
"press left, then walk" unreliable in a way that looks like a detection
bug.

**The probe deliberately does not read the sidebar's highlight colour.**
That signal is exactly what is under suspicion, so using it to diagnose
itself would be circular. Instead focus is inferred from CONSEQUENCE: press
one arrow key and see which half of the screen reacted.

    content text changed  -> focus was in the content panel
    sidebar mark changed  -> focus was in the sidebar
    neither changed       -> the key did nothing (an end stop, or lost)

Content text is the reliable half of this pipeline (it is what every
working tool already reads), so it anchors the diagnosis while the
suspect signal is only reported alongside, never trusted.

One key per step, never composed sequences -- composing is what made the
earlier attempt unreadable. Arrow keys only: no enter, no esc, so nothing
can open a dialog or change a setting.

    py -3.13 study_focus_probe.py --serial-port COM3
"""
import argparse
import json
import os
import time

from biostools.navigate import SIDEBAR_MAX_X
from biostools.screen import normalize
from biostools.session import BiosSession
from ocr import DEFAULT_ENGINE, ENGINE_CHOICES

# Steps are single keys. The sequence alternates so that if `left` toggles,
# the second `left` lands with focus already in the sidebar -- the exact
# condition that would expose a toggle and that the earlier composed
# attempt could not separate.
DEFAULT_SEQUENCE = ["down", "left", "down", "left", "down", "right", "down"]


def split_lines(reading):
    """Sidebar lines vs content lines, by the same x threshold navigate uses."""
    lines = [line for block in reading.get("blocks", ())
             for line in block.get("lines", ())]
    sidebar = [l for l in lines if l["bbox"]["left"] < SIDEBAR_MAX_X]
    content = [l for l in lines if l["bbox"]["left"] >= SIDEBAR_MAX_X]
    return sidebar, content


def is_volatile(token):
    """Text that changes on its own, with no keypress involved.

    The Main page carries a live clock (`System Time`), so a raw content
    signature differs between ANY two reads a second apart -- which made
    the first version of this probe report "content reacted" for every
    single key, including ones that could not possibly have touched the
    content panel. Measured elsewhere in this project too: flipping only
    the clock from 16:30:48 to :49 changed the engine's whole content
    fingerprint (see the note on screen_id in the project docs).

    Anything mostly digits is dropped: clock, sensor readings, fan RPM.
    That loses real changes whose only difference is a number, so this
    probe is blind to a cursor moving between two purely-numeric rows --
    acceptable here, since it is diagnosing WHICH PANEL reacted, and a
    panel that reacted almost always changes some non-numeric text too.
    """
    if not token:
        return True
    digits = sum(c.isdigit() for c in token)
    return digits * 2 >= len(token)


def sidebar_marked(reading):
    """The marked line **within the sidebar only**.

    `legacy_cursor` searches the whole screen by design (it has to pick
    between the sidebar tab and the content row the cursor is on). Used
    raw here it latches onto content lines: measured 2026-08-24, it
    reported `'11:35:01'` -- the live clock -- as the "sidebar" cursor,
    which made this probe's verdicts nonsense. Restricting it to sidebar
    geometry first is what makes the two halves of this probe independent,
    which is the whole point of comparing them.
    """
    sidebar, _ = split_lines(reading)
    marked = [l for l in sidebar if l.get("highlighted")]
    if len(marked) != 1:
        return None  # zero, or the ambiguous multi-mark case: no answer
    return marked[0]["text"]


def probe(session):
    """One observation: what the content says, and what the sidebar claims."""
    reading = session.read_cursor()
    sidebar, content = split_lines(reading)
    marked = sidebar_marked(reading)
    # The content panel's own highlight. On a settings LIST (Advanced and
    # friends) the row under the cursor is drawn with a dark bar that
    # selection.py reads reliably -- that is how `cpu_temperature` works --
    # so this catches content-side cursor movement that changes no text.
    # On a FIELD page (Main) it stays None: field focus there is drawn as a
    # border ring, which no channel in this project measures (see
    # docs/specs/p-specs/campo-focado-por-borda-sem-canal-no-e7.md).
    content_marks = [l["text"] for l in content if l.get("highlighted")]
    return {
        # Sorted set, not reading order: OCR can reorder equal-y lines
        # between reads, and that would masquerade as a real change.
        "content": sorted({t for t in (normalize(l["text"]) for l in content)
                           if not is_volatile(t)}),
        "sidebar_marked": marked,
        "content_marked": content_marks[0] if len(content_marks) == 1 else None,
        "sidebar_dark": [l["text"] for l in sidebar
                         if l.get("fg_color") and sum(l["fg_color"]) < 500],
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--camera-source", default="0")
    parser.add_argument("--engine", choices=ENGINE_CHOICES, default=DEFAULT_ENGINE)
    parser.add_argument("--resolution", default="1280x720")
    parser.add_argument("--serial-port", required=True)
    parser.add_argument("--sequence", default=",".join(DEFAULT_SEQUENCE),
                        help="Comma-separated arrow keys, pressed ONE at a time "
                             "with a full reading between each")
    parser.add_argument("--out-dir", default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    resolution = tuple(int(v) for v in args.resolution.lower().split("x"))
    keys = [k.strip() for k in args.sequence.split(",") if k.strip()]

    unsafe = [k for k in keys if k not in ("up", "down", "left", "right")]
    if unsafe:
        raise SystemExit(f"only arrow keys allowed in this probe, got: {unsafe}")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or os.path.join("captures", f"focus_probe_{stamp}")
    os.makedirs(out_dir, exist_ok=True)

    log = []
    with BiosSession(camera_source=args.camera_source, engine=args.engine,
                      resolution=resolution,
                      serial_port=args.serial_port) as session:
        before = probe(session)
        print(f"estado inicial: sidebar_marked={before['sidebar_marked']!r}  "
              f"({len(before['content'])} linhas de conteudo)")
        print(f"                itens escuros na barra: {before['sidebar_dark']}\n")

        for i, key in enumerate(keys):
            session.press(key)
            after = probe(session)

            gone = set(before["content"]) - set(after["content"])
            new = set(after["content"]) - set(before["content"])
            # One token appearing/vanishing is usually OCR flicker on a
            # marginal glyph, not the panel reacting. Two is a real change:
            # a scrolled list loses a row at one end and gains one at the
            # other, and a page switch replaces most of the panel.
            content_moved = (len(gone | new) >= 2
                             or after["content_marked"] != before["content_marked"])
            sidebar_moved = after["sidebar_marked"] != before["sidebar_marked"]

            if content_moved and not sidebar_moved:
                verdict = "CONTEUDO reagiu -> foco estava no conteudo"
            elif sidebar_moved and not content_moved:
                verdict = "BARRA reagiu -> foco estava na barra lateral"
            elif content_moved and sidebar_moved:
                verdict = "AMBOS mudaram -> trocou de pagina (barra muda o conteudo)"
            else:
                # NOT the same as "the key was lost". On a field page the
                # focused field is marked by a border ring, which nothing
                # in this project measures, so a cursor moving between
                # fields changes neither signal here. Measured 2026-08-24
                # on the Main page: seven arrow presses in a row, zero
                # observable change, on a machine whose cable was
                # demonstrably working minutes earlier.
                verdict = ("INDISTINGUIVEL -> nenhum sinal mudou; pode ser "
                           "tecla sem efeito OU foco no conteudo com marcacao "
                           "por borda (invisivel para este probe)")

            print(f"[{i}] {key!r}")
            print(f"     sidebar_marked: {before['sidebar_marked']!r} -> "
                  f"{after['sidebar_marked']!r}")
            print(f"     escuros: {before['sidebar_dark']} -> {after['sidebar_dark']}")
            print(f"     conteudo mudou: {content_moved}"
                  f"  (-{len(gone)} +{len(new)})")
            if gone or new:
                print(f"       saiu : {sorted(gone)[:4]}")
                print(f"       entrou: {sorted(new)[:4]}")
            print(f"     => {verdict}\n")

            log.append({
                "step": i, "key": key,
                "sidebar_before": before["sidebar_marked"],
                "sidebar_after": after["sidebar_marked"],
                "dark_before": before["sidebar_dark"],
                "dark_after": after["sidebar_dark"],
                "content_moved": content_moved,
                "content_gone": sorted(gone),
                "content_new": sorted(new),
                "sidebar_moved": sidebar_moved,
                "verdict": verdict,
            })
            before = after

    with open(os.path.join(out_dir, "focus_probe.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    # -- what the `left` presses did, side by side --------------------------
    lefts = [e for e in log if e["key"] == "left"]
    print("=" * 60)
    if len(lefts) >= 2:
        print("comparando os 'left' (a pergunta do toggle):")
        for e in lefts:
            print(f"  passo {e['step']}: {e['verdict']}")
        print()

    # The decisive read is what the `down` AFTER each `left` did: if `left`
    # always forces the sidebar, every post-left `down` moves the sidebar.
    post_left = [log[i + 1] for i, e in enumerate(log)
                 if e["key"] == "left" and i + 1 < len(log)
                 and log[i + 1]["key"] in ("down", "up")]
    if len(post_left) >= 2:
        print("o que o 'down' logo APOS cada 'left' fez (o teste decisivo):")
        for e in post_left:
            print(f"  passo {e['step']}: {e['verdict']}")
        moved_sidebar = [e["sidebar_moved"] and not e["content_moved"]
                         for e in post_left]
        blind = [not e["sidebar_moved"] and not e["content_moved"]
                 for e in post_left]

        # Any blind step poisons the comparison: "nothing observed" is not
        # evidence of "nothing happened", so a mix of moved/blind cannot be
        # read as a toggle. Saying so is the point -- an earlier version of
        # this script did draw that conclusion, and it was wrong.
        if any(blind):
            print("\n=> INCONCLUSIVO: pelo menos um 'down' apos 'left' nao "
                  "produziu sinal observavel, e este probe nao distingue "
                  "'tecla sem efeito' de 'foco no conteudo marcado por "
                  "borda'. NAO da para concluir alternancia nem forca daqui. "
                  "Rode numa pagina cujo conteudo seja uma LISTA (ex. "
                  "Advanced), onde a linha sob o cursor tem barra escura "
                  "detectavel, em vez de uma pagina de campos (Main).")
        elif all(moved_sidebar):
            print("\n=> 'left' entregou o foco a barra TODA vez: "
                  "comporta-se como FORCA, nao como alterna.")
        elif not any(moved_sidebar):
            print("\n=> nenhum 'down' apos 'left' mexeu na barra: 'left' nao "
                  "esta entregando o foco a barra nesta tela.")
        else:
            print("\n=> resultado MISTO entre os 'left', com sinal observavel "
                  "em todos os passos -- consistente com ALTERNANCIA (o 1o "
                  "entrega, o 2o devolve).")

    print(f"\nlog salvo em {out_dir}")


if __name__ == "__main__":
    main()
