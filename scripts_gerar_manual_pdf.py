"""One-off: render docs/reference/MANUAL_APRESENTACAO_BIOS.md as a PDF.

Not part of the shipped tool set -- a formatting pass over content that
already exists as the markdown source of truth. Re-run after editing the
.md if the PDF needs to stay in sync.
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    ListFlowable, ListItem, Paragraph, Preformatted, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

INK = colors.HexColor("#171b1d")
MUTED = colors.HexColor("#565f63")
ACCENT = colors.HexColor("#1e6b8c")
ACCENT_SOFT = colors.HexColor("#dcebf1")
BORDER = colors.HexColor("#d3d8d8")
CODE_BG = colors.HexColor("#e3e7e7")

styles = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=25,
                            leading=29, textColor=INK, spaceAfter=4),
    "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=11.5,
                               leading=16, textColor=MUTED, spaceAfter=18),
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=15.5,
                         leading=19, textColor=ACCENT, spaceBefore=20, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12,
                         leading=15, textColor=INK, spaceBefore=12, spaceAfter=5),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14.5,
                           textColor=INK, spaceAfter=7, alignment=4),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=9, leading=12.5,
                            textColor=MUTED, spaceAfter=6),
    "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=10,
                             leading=14, textColor=INK),
    "code": ParagraphStyle("code", fontName="Courier", fontSize=8.7, leading=12,
                           textColor=INK, backColor=CODE_BG, borderPadding=6,
                           leftIndent=2),
    "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9.3,
                         leading=12, textColor=colors.white),
    "td": ParagraphStyle("td", fontName="Helvetica", fontSize=9.3, leading=13,
                         textColor=INK),
}


def h1(text):
    return Paragraph(text, styles["h1"])


def h2(text):
    return Paragraph(text, styles["h2"])


def body(text):
    return Paragraph(text, styles["body"])


def code(text):
    return Preformatted(text, styles["code"])


def bullets(items):
    return ListFlowable(
        [ListItem(Paragraph(it, styles["bullet"]), spaceAfter=4) for it in items],
        bulletType="bullet", start="•", leftIndent=14,
    )


def kv_table(rows, col_widths):
    header = [Paragraph(h, styles["th"]) for h in rows[0]]
    data = [header] + [[Paragraph(c, styles["td"]) for c in r] for r in rows[1:]]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f6")]),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


story = []
S = Spacer(1, 4)

story.append(Paragraph("Manual da Estação de Leitura de BIOS", styles["title"]))
story.append(Paragraph(
    "Guia de referência para montar a estação, apresentar o sistema ou "
    "entender o que ele faz — para qualquer pessoa, não só quem acompanhou "
    "o projeto.", styles["subtitle"]))

story.append(body(
    "Complementa (não substitui) <b>PROCESSO_OCR.md</b> (como a leitura da "
    "tela funciona por dentro) e o F-spec <b>camada-de-tools-consulta-bios.md</b> "
    "(lista técnica completa de tools). Este documento é sobre <b>usar</b> "
    "o sistema, não sobre como ele é implementado."))

story.append(h1("O que o sistema faz, em uma frase"))
story.append(body(
    "Alguém pergunta em português, em voz normal (“qual a temperatura "
    "da CPU?”); o sistema lê a tela de uma BIOS de verdade por câmera, "
    "aperta as teclas necessárias por um cabo físico, e responde com o "
    "valor real — sem digitar nada na BIOS, sem ninguém abrir o Setup "
    "manualmente."))

story.append(h1("As três máquinas"))
story.append(body(
    "O sistema roda em três máquinas separadas, cada uma com um papel. A "
    "intermediária é o único ponto que fala com as outras duas — a BIOS "
    "nunca fala direto com a IA, e quem pergunta nunca toca em nenhuma "
    "das duas."))
story.append(S)
story.append(kv_table(
    [["Máquina", "Papel"],
     ["Intermediária (Windows)",
      "Onde o código roda. Tem a câmera (lê a tela) e o cabo atuador "
      "(aperta teclas). É onde a pessoa digita a pergunta."],
     ["BIOS alvo",
      "A máquina sendo testada/apresentada. O cabo se conecta nela como "
      "se fosse um teclado USB comum — ela não sabe que está sendo "
      "operada por software."],
     ["IA",
      "Roda o modelo de linguagem (Lemonade Server) que interpreta a "
      "pergunta, escolhe qual leitura fazer, e escreve a resposta em "
      "português. Fica sempre numa máquina separada, com NPU dedicada."]],
    col_widths=[110, 330]))
story.append(S)
story.append(code(
    "  pessoa                intermediaria              BIOS alvo\n"
    "    |  pergunta (pt-br)      |                          |\n"
    "    +------------------------>                          |\n"
    "    |                        |-- camera USB: le a tela ->|\n"
    "    |                        |-- cabo COM: envia teclas ->|\n"
    "    |                        |                          |\n"
    "    |                        |      maquina de IA\n"
    "    |                        |-- rede: pergunta + tools ->|\n"
    "    |                        |<- resposta em texto -------|\n"
    "    |<- resposta -------------                          |"))

story.append(h1("Montando uma estação do zero"))
story.append(body(
    "Sequência recomendada — nessa ordem, porque cada fase depende da "
    "anterior estar confirmada."))

story.append(h2("1. Máquina de IA"))
story.append(code("lemonade backends install flm:npu\n"
                  "lemonade pull qwen3.6-moe-35b-a3b-FLM"))
story.append(body(
    "Esse é o modelo que o assistente usa de fato (mais preciso na "
    "escolha de tool, mais lento). É um download grande; comece por ele "
    "com antecedência, não na véspera da apresentação."))
story.append(body(
    "Por padrão o Lemonade escuta só em <font face=\"Courier\">127.0.0.1</font> "
    "(loopback) — inacessível de outra máquina. Para uma demo ao vivo, "
    "reconfigurar para escutar na rede é mais confiável que depender de um "
    "túnel SSH manual (mais uma coisa que pode cair no meio da "
    "apresentação) — embora a estação atual já tenha a opção de abrir esse "
    "túnel direto pela GUI, sem precisar de terminal separado."))
story.append(code("lemonade config set host=0.0.0.0"))
story.append(body("Confirme que responde <b>de outra máquina</b>, não da própria:"))
story.append(code("curl http://<ip-da-maquina-de-ia>:13305/api/v1/models"))

story.append(h2("2. Máquina intermediária"))
story.append(code("py -3.13 -m pip install -r requirements.txt\n"
                  "py -3.13 test_biostools.py"))
story.append(body(
    "O segundo comando roda a suíte offline — sem câmera, sem cabo. Se "
    "não terminar em <font face=\"Courier\">tudo passou</font>, o problema "
    "é do código/ambiente; resolva antes de tocar em qualquer hardware."))
story.append(body("Depois, confirme que a máquina enxerga a câmera e o cabo:"))
story.append(code(
    "py -3.13 -c \"from capture import list_camera_devices; "
    "print(list_camera_devices())\"\n"
    "py -3.13 -c \"from actuator import list_serial_ports; "
    "print(list_serial_ports())\""))
story.append(body(
    "O cabo usa um adaptador USB-serial Prolific PL2303 — o Windows "
    "normalmente instala o driver sozinho ao plugar, se a máquina tiver "
    "internet no momento. Se não reconhecer, baixe o driver oficial em "
    "www.prolific.com.tw."))

story.append(h2("3. Ligar as pontas"))
story.append(body(
    "<font face=\"Courier\">assistant.ask(pergunta, sessao, host=..., "
    "port=...)</font> aceita o endereço da máquina de IA como parâmetro — "
    "não precisa editar código, só apontar para o IP certo (ou usar o "
    "campo de túnel SSH da GUI)."))

story.append(h2("4. Bancada física"))
story.append(bullets([
    "<b>Câmera perto e alinhada com a tela</b>, não enquadrando o monitor "
    "inteiro de longe — já aconteceu de o OCR ler zero palavras com o "
    "texto pequeno demais em pixels.",
    "<b>Cabo USB-KM232</b>: ponta USB na máquina BIOS alvo (aparece pra "
    "ela como teclado comum, sem driver); ponta serial no adaptador "
    "USB-serial, e este na máquina intermediária.",
    "BIOS alvo ligada e parada no Setup (tela Main visível) antes de "
    "começar.",
]))

story.append(h1("O que perguntar"))
story.append(body(
    "Qualquer pergunta em português normal. A IA escolhe sozinha qual "
    "leitura fazer — quem pergunta não precisa saber nome de tool "
    "nenhuma."))
story.append(body(
    "<b>Para abrir</b>, as duas melhores — mostram câmera, OCR e cabo "
    "funcionando juntos em tempo real, com um número que muda a cada "
    "leitura:"))
story.append(bullets([
    "“Qual a temperatura da CPU?”",
    "“Qual a rotação do cooler?”",
]))

topics = [
    ("Sistema", "versão e data de build da BIOS · versão e data de "
     "build do EC · nome do produto, fabricante e número de série "
     "· data e hora configuradas · endereço MAC · "
     "quantidade e frequência da memória RAM · versão do Intel "
     "Management Engine."),
    ("Segurança", "o TPM está habilitado, e em que estado · a BIOS "
     "pede senha só no Setup ou também no boot · a proteção de "
     "escrita da flash está ativa, e o downgrade de BIOS é permitido "
     "· política para armazenamento USB removível · o Absolute "
     "Persistence está ativo, versão e status da interface."),
    ("Boot", "Fast Boot habilitado · ordem de boot configurada "
     "· estado do NumLock na inicialização · tempo que o logo "
     "fica visível no POST · atalho de boot F11 e PXE após Wake on "
     "LAN · boot por dispositivo removível, checagem S.M.A.R.T. e "
     "reflash do ME."),
    ("Energia, vídeo e periféricos", "quais eventos acordam a máquina "
     "(LAN, PCI/PCIE, teclado/mouse, RTC) · USB Charger habilitado "
     "· modo do controlador SATA · display primário e memória "
     "de vídeo alocada (GTT/Aperture/DVMT) · virtualização (VT-d/"
     "VT-x) habilitada · Audio DSP habilitado · quais "
     "dispositivos onboard estão ligados (vídeo, áudio, SATA, M.2, "
     "leitor de cartão)."),
]
for title, text in topics:
    story.append(h2(title))
    story.append(body(text))

story.append(h2("Se a pergunta não tiver tool nomeada"))
story.append(body(
    "O sistema ainda tenta: primeiro no índice de rótulos já colhido "
    "desta máquina, depois varrendo a tela ao vivo antes de desistir. "
    "Funciona para qualquer ajuste real da BIOS, mesmo bem específico — "
    "“o Network Stack está habilitado?”, “qual o tempo de "
    "espera do PXE Boot?”"))
story.append(body(
    "<b>Se o ajuste realmente não existir nesta BIOS</b>, a resposta é "
    "honesta sobre isso — “não existe nesta máquina” é uma "
    "resposta certa, não uma falha do sistema. Vale enquadrar isso como "
    "recurso na hora de apresentar: o sistema nunca chuta um valor que "
    "não leu."))

story.append(h2("Evitar por enquanto"))
story.append(body(
    "“Quais opções tem no menu principal?” e “o que a tela "
    "Main mostra?” (as tools <font face=\"Courier\">main_menu</font>/"
    "<font face=\"Courier\">main_info</font>) estão bloqueadas por um "
    "problema conhecido: quando o cursor está na barra lateral, o motor "
    "de percepção não consegue distinguir a aba ativa do cursor — as "
    "duas desenham uma barra escura quase idêntica. Detalhe técnico no "
    "F-spec da camada de tools."))

story.append(h1("Se algo der errado ao vivo"))
story.append(h2("A IA demora para responder"))
story.append(body(
    "O modelo principal roda localmente, sem depender de internet, e "
    "pode levar de alguns segundos até ~30s numa pergunta mais "
    "elaborada. Não é travamento — vale narrar isso em vez de esperar "
    "em silêncio."))
story.append(h2("A IA não responde de jeito nenhum"))
story.append(body(
    "Sintoma: erro de “chamada ao modelo falhou”. Normalmente é "
    "a máquina de IA inacessível pela rede (confira o host/porta, ou o "
    "túnel SSH). Enquanto isso, cada tool ainda pode ser chamada "
    "diretamente pela janela “Ver tools” da GUI, sem depender "
    "da IA."))
story.append(h2("O cabo para de responder"))
story.append(body(
    "Já aconteceu de verdade numa sessão de testes — a porta COM "
    "continuava visível pro Windows, mas o protocolo do cabo parou de "
    "responder. Causa mais provável: a ponta USB do cabo se soltou, ou a "
    "máquina BIOS alvo entrou em suspensão. Reconectar a ponta USB e "
    "confirmar que a máquina alvo está acordada resolve na maioria dos "
    "casos."))
story.append(h2("A resposta parece errada ou incompleta"))
story.append(body(
    "O sistema nunca inventa um valor: se a narração da IA não bate "
    "palavra por palavra com o que a tool leu da tela, ele descarta a "
    "narração e mostra o texto bruto da leitura em vez disso. Uma "
    "resposta “estranha” tem mais chance de ser uma leitura "
    "real da tela do que uma alucinação — vale conferir a tela antes de "
    "assumir que é bug."))

story.append(h1("Antes da apresentação"))
story.append(bullets([
    "<b>Rode o checklist inteiro na estação que vai ser usada de "
    "verdade, com antecedência — não na véspera.</b> Uma BIOS "
    "“idêntica” em outra unidade física já se comportou de "
    "forma sutilmente diferente numa sessão de testes deste projeto "
    "(tempo de rolagem de página variou por página); só apareceu "
    "rodando contra o hardware real. Melhor descobrir isso com tempo "
    "de corrigir.",
    "Prefira cabo de rede a wifi entre a intermediária e a máquina de "
    "IA, se der — é o ponto mais frágil se a rede cair no meio de uma "
    "pergunta.",
    "Tenha uma ordem de perguntas em mente (abrir com sensor ao vivo, "
    "aprofundar por assunto) em vez de ler a lista solta — fica mais "
    "natural e mais fácil de recuperar se algo falhar no meio.",
]))

doc = SimpleDocTemplate(
    "docs/reference/MANUAL_APRESENTACAO_BIOS.pdf", pagesize=A4,
    topMargin=20 * mm, bottomMargin=18 * mm,
    leftMargin=20 * mm, rightMargin=20 * mm,
    title="Manual da Estacao de Leitura de BIOS",
)
doc.build(story)
print("PDF gerado.")
