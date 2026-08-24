# Navegação ancorada na barra lateral (ir de qualquer página para qualquer outra)

## Objetivo

Levar a BIOS de **qualquer** página de topo (Main, Advanced, Security, Boot, Event Log, ...) para **qualquer outra**, de forma verificada, sem depender de enxergar o cursor na barra lateral — que é exatamente o sinal que o caminho legado não consegue ler de forma confiável (ver [`../p-specs/deteccao-cursor-barra-lateral-instavel-entre-frames.md`](../p-specs/deteccao-cursor-barra-lateral-instavel-entre-frames.md)).

Existe porque essa era a queixa central do projeto: *"estou na Main e não consigo ir para a Advanced"*. A navegação anterior caminhava pela barra lateral relendo o cursor a cada passo; com foco na barra existem **duas** barras escuras ao mesmo tempo (a página exibida e o cursor), e `selection.py` sempre devolve a da página exibida — então a caminhada via o mesmo item para sempre. A troca é conceitual: em vez de *observar* onde o cursor está, **levá-lo a um ponto conhecido (ancorar), contar a partir dali, e verificar a chegada**.

## Escopo

- **Dentro**: `navigate.enter_main_menu_screen_by_count` (o algoritmo), `navigate.enter_main_menu_screen` (a porta de entrada usada por todas as tools), `navigate.setup_icon_focused` (a âncora), `navigate.sidebar_active` (verificação de chegada), `navigate.sidebar_limit` (geometria da barra proporcional à largura do frame).
- **Fora**: navegação *dentro* do painel de conteúdo (submenus, campos) — continua sendo `move_to`/`Step`. Fora também: qualquer alteração de configuração; esta feature só troca de página.
- **`save_and_exit` fica de fora da lista padrão de passeio** (`study_menu_tour.py`) de propósito: toda opção daquela página compromete ou abandona configuração.
- **O caminho antigo (caminhada observando o cursor) foi REMOVIDO, não mantido como fallback.** Ver "Detalhes técnicos".

## Comportamento esperado

Entrada: uma sessão viva e um nome canônico de tela (`labels.SCREENS`). Saída: `NavigationResult`, com `ok=True` só quando a chegada foi *verificada na tela*.

Algoritmo (`enter_main_menu_screen_by_count`):

1. Lê as entradas da barra lateral pela tela (`sidebar_entries`) e acha o índice do alvo. Se não conseguir ler nada → `BLIND`; se o alvo não estiver na lista → `CYCLED`.
2. `left` — entrega o foco à barra lateral (o cursor pousa dentro dela).
3. `N + 2` × `up` — **a lista não dá a volta**, então isso encosta o cursor no topo de forma determinística, venha ele de onde vier. As duas pressões extras cobrem a seta de voltar acima das entradas e um eventual item que o OCR tenha perdido; pressionar a mais contra um batente é inofensivo.
4. **Verifica a âncora** via `setup_icon_focused(frame)`. Se não confirmar (`False` ou `None`), **aborta sem apertar ENTER**.
5. `(índice do alvo + 1)` × `down` — o topo é a **seta Setup**, não a primeira entrada, então a primeira entrada custa 1 `down`. Calibrado ao vivo: ancorado + 1 `down` + ENTER abre Main.
6. `enter`.
7. **Verifica a chegada** com `sidebar_active(reading)`. Depois do ENTER a ambiguidade some — cursor e página exibida são o mesmo item, sobra uma única barra escura, que é o caso que `selection.py` lê certo.
8. Se aparecer diálogo (`looks_like_dialog`), manda **um** ESC e reporta falha. Diálogo nunca é respondido com ENTER.

Casos de borda:

- Barra lateral coberta por diálogo modal → `setup_icon_focused` devolve `None` ("não consigo dizer"), deliberadamente distinto de `False` ("não está ancorado"). O primeiro não justifica apertar mais teclas; o segundo justificaria.
- ESC no topo da BIOS **abre** "Discard Changes and Exit"; ESC sobre o diálogo o **fecha**. Confirmado ao vivo.

## Detalhes técnicos

### A âncora é um ÍCONE, não texto — o insight central

O topo da barra lateral é um ícone circular de voltar, ao lado do texto "Setup". A ideia veio do usuário: *"é só o software ver que o Setup está selecionado"*.

O sinal **não está no texto**. Medido: a palavra "Setup" renderiza **bit a bit idêntica** com e sem o cursor nela — fg `[255,255,255]`, bg `[253,220,178]` nos dois estados. O que muda é o ícone: **anel (contorno)** quando o cursor está em outro lugar, **disco preenchido** quando o cursor está nele.

Por isso todas as tentativas via OCR falhavam: `selection.py` só amostra cor **dentro de caixa de texto do OCR**, e isto é um ícone — não existe caixa para ele.

### A medida

`setup_icon_focused` mede a **fração de pixels quase-brancos** (`min` dos canais BGR > 235) dentro de `_SETUP_ICON_BOX`, definido em frações do frame (medido x 18..56, y 78..115 em 1280x720) para sobreviver a outra resolução de captura.

| Estado | Fração de pixels quase-brancos |
|---|---|
| Cursor em outro lugar (anel) | **0,2496** — bit a bit **idêntico** em 8 frames diferentes |
| Cursor ancorado (disco) | **0,4260 – 0,4379** |
| Barra coberta por diálogo modal | **1,0** |

Limiares: `_ICON_FILLED_MIN = 0.33` (bem longe dos dois valores reais) e `_ICON_OBSCURED_MIN = 0.90`. O fato de o valor não-ancorado ser *bit a bit idêntico* entre frames prova que é renderização pura, não ruído de câmera — é isso que torna o limiar seguro em vez de sorte.

### Por que ancorar, e não contar de onde o cursor está

Uma versão anterior assumia que o cursor sempre começava uma posição acima da primeira entrada. Não começa — depende do que aconteceu antes. Quando a suposição estava errada, a contagem parava na **seta Setup**, onde ENTER abre **"Discard Changes and Exit"**. Foi assim que esse diálogo apareceu repetidamente na máquina real durante a sessão.

### Por que o caminho antigo foi removido e NÃO deve ser reintroduzido

A caminhada observando o cursor não era só ineficaz, era **ativamente perigosa**: por não distinguir a barra do cursor da barra da página ativa, com a página **já no alvo** ele concluía "cheguei em 0 passos" e apertava ENTER com o cursor parado na seta Setup — de novo o "Discard Changes and Exit". Não reintroduzir como fallback.

### Por que `sidebar_active` e não `legacy_cursor`

`legacy_cursor` varre a tela inteira. Quando conteúdo e barra estão ambos marcados (o caso normal logo após abrir uma página) ele devolve o cursor do **conteúdo**. A verificação de chegada precisa da marca **dentro da geometria da barra lateral**, então a seleção por geometria tem que vir antes de qualquer desempate.

### Correções de infraestrutura que a navegação depende (mesma sessão)

- **`BiosSession.press()` drena o buffer da câmera** (`_flush`, `FLUSH_FRAMES=12`) e `_open_camera` pede `CAP_PROP_BUFFERSIZE=1`. Motivo medido: `wait_stable()` decide que a tela assentou comparando frames consecutivos — e uma fila de frames bufferizados de **antes** da tecla são idênticos entre si, passam no teste e são devolvidos como "a tela estável". Leitura confiantemente errada. Pego ao vivo: um diálogo já fechado apareceu como aberto em **duas** leituras seguidas.
- **`registry._close_opened`** substituiu o loop de ESCs cegos do `Tool.restore`: relê a tela entre cada ESC e usa `looks_like_dialog()` (casa frases conhecidas OU o par Ok+Cancel); se aparecer diálogo, manda um ESC e para.
- **`SIDEBAR_MAX_X=300`** era pixel absoluto calibrado em 1280x720 e zerava a barra lateral nas fixtures 4K de `captures/` → virou `sidebar_limit(reading)`, proporcional à largura via `SIDEBAR_MAX_X_RATIO`.
- **`cpu_temperature`**: a perna 1 declarava `Step(to="advanced", hint="nav_menu", activate=False)` — ENTER nunca era pressionado, o cursor chegava em "Advanced" mas a página exibida continuava a anterior, e a perna 2 procurava "Hardware Monitor" no conteúdo da tela errada. `activate` agora é `True` por padrão. A perna 2 também perdeu o `focus_key="right"`, que existia só para compensar a perna 1 não abrir a página; depois do ENTER o foco já está no conteúdo, e o `right` passou a jogar o foco para a coluna de ícones da direita.
- **`enter_main_menu_screen`** tinha `activate_key=None`, documentado como "mover o cursor já troca a página nesta BIOS". Isso estava **medido errado** — fotografado: com a página em Main e o cursor movido, a barra desenha duas barras escuras e o conteúdo só troca com ENTER. O padrão agora é `"enter"`.

## Critérios de aceite

**Ao vivo (hardware real Positivo, HDMI 1280x720 + cabo USB-KM232 em COM3):**

- `cpu_temperature` respondeu partindo de **Main (63 C), Advanced (64 C), Security (63 C), Boot (63 C) e Event Log (60 C)** — inclusive de páginas **abaixo** do alvo na lista, que é o caso que a caminhada antiga nunca resolveu.
- `study_menu_tour.py` (reescrito sobre esta navegação) visitou **5/5** menus numa passada (main, advanced, security, boot, event_log), salvando impressão digital de conteúdo + frame de cada um em `captures/menu_tour_<timestamp>/`.

**Offline:** suíte `test_biostools.py` passando, com o teste novo `test_setup_icon_anchor()`, que mede a detecção contra frames **reais** em `captures/handshake/*.png`. O `FakeBios` sintetiza frame do tamanho da própria fixture, com o ícone na fração certa — o teste de pixels não é falsificado para passar.

## Status

**Concluída — 2026-08-24.**

## Questões em aberto

- **A detecção do ícone é calibrada para a UI da Positivo.** A caixa `_SETUP_ICON_BOX`, os limiares `_ICON_FILLED_MIN`/`_ICON_OBSCURED_MIN` e a própria premissa "o topo da barra é uma seta de voltar, não a primeira entrada" são medidas dessa BIOS específica. Quando os outros **2 modelos de BIOS da fábrica** entrarem, isso precisa de revisão: outro modelo pode não ter o ícone, pode marcá-lo por outro sinal, ou pode ter a primeira entrada no topo (o que muda o `+1` da contagem). O algoritmo (ancorar → contar → verificar) deve sobreviver; a calibração não.
- O teto de leitura do cursor na barra lateral continua real, só deixou de bloquear — ver [`../p-specs/deteccao-cursor-barra-lateral-instavel-entre-frames.md`](../p-specs/deteccao-cursor-barra-lateral-instavel-entre-frames.md).
