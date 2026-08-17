# Glare e moiré degradam o OCR em captura ao vivo (não é o motor de OCR)

## O problema
Analisando 5 capturas reais de 2026-08-12 (`20260812-160027_auto`, `20260812-154431_auto`, `20260812-153950_auto`, `20260812-152336_auto`, `20260812-151104_manual`) contra o pedido de investigar "erros de leitura" do OCR, a conclusão é que **o motor de OCR não é a causa** dos erros observados nessas fotos. `../../studies/estudo-motores-ocr.md` já havia estabelecido que `rapidocr-openvino` (default) e `paddleocr` empatam em acurácia (11/11 no gabarito formal); esta análise, sobre capturas reais fora do gabarito, aponta duas causas de captura/ambiente presentes nas 5 fotos, não de motor: **glare** (reflexo de luz saturando parte da tela) e **moiré** (interferência câmera×tela LCD).

### Glare — presente nas 5 capturas
Uma mancha de reflexo de luz ambiente satura parte do painel escuro da BIOS. Onde ela cobre texto, a linha some inteira do OCR (não aparece garbled, simplesmente não existe nos primitivos) ou fica cortada pela metade. Casos concretos, com primitive IDs, de `captures/20260812-160027_auto.json` e `captures/20260812-154431_auto.json`:

- `"Arrecclevel"` (154431, p039, conf 0.788) e `"Arrecclevel"`/`"ArcasclAvel"` (160027, p045, conf 0.8393) — deveria ser "Access Level"; o texto real na tela está sobre a mancha de glare, quase ilegível mesmo a olho humano na foto.
- `"etween Time elements,"` (160027, p035) — falta o início ("Set the Time. Use Tab to switch b...") porque essa parte cai na área saturada de brilho. Fisicamente apagado na foto, não é erro de leitura do motor.
- `"alogy"` (160027, p036, conf 0.9297) — cauda de "Intel BIOS Guard Technology", mesmo mecanismo.
- Em `20260812-154431_auto.json` o glare é forte o bastante pra apagar **3 linhas inteiras de rótulos** (Intel BIOS Guard Technology, BIOS Version, BIOS Build Date, Platform BIOS Type) — nem aparecem garbled nos primitivos, simplesmente não existem no OCR.
- `"DD(YYYY)"` (154431, p037, conf 0.9523) — o rótulo completo seria algo como "BIOS Build Date (MM/DD/YYYY)"; o glare comeu a maior parte do texto e a barra "/" restante foi lida como "(".

### Moiré — presente em 100% das 5 capturas
Ondulações arco-íris diagonais visíveis em todas as capturas, degradando nitidez de fonte pequena. Provável causa dos erros de caractere pontuais que acontecem *fora* da área de glare — e a evidência mais forte disso é que são **inconsistentes entre capturas da mesma tela**, o que descarta erro sistemático de leitura do motor:
- `"Versian"` em vez de `"Version"` (160027, p048, conf 0.9699) — a mesma frase é lida corretamente como `"Version"` em `154431`. Ruído de frame a frame, não erro sistemático.
- `"Year,1998-2099"` em vez de `"Year: 1998-2099"` (dois-pontos lido como vírgula, 160027 p028 conf 0.9516) contra `"Year.1998-2099"` (ponto, 154431 p028 conf 0.9615) — mesma tela, dois erros diferentes de pontuação em duas capturas.

## Onde ele mora
Entrada do pipeline (captura ao vivo via `../d-specs/webcam-ugreen-4k.md`), antes de qualquer estágio de percepção processar a imagem — os primitivos `symbolic:rapidocr-openvino` do JSON de percepção já chegam degradados. Não é um estágio específico de `perception/` que pode corrigir isso; a informação já está parcialmente destruída na foto de entrada. Relacionado a `retificacao-e1-inatingivel-sem-moldura-visivel.md` (mesma sessão de investigação, mesmo conjunto de 5 capturas), mas causa e correção são independentes: aquele é um problema de enquadramento geométrico, este é de iluminação e amostragem óptica câmera×tela.

## Por que existe
- **Glare**: luz ambiente refletindo na superfície da tela em direção à câmera. Depende de ângulo de câmera, posição de fontes de luz e ausência de filtro polarizador — nenhum desses três foi controlado nas capturas de 2026-08-12.
- **Moiré**: padrão de interferência clássico entre a grade de subpixels do monitor LCD e o sensor da câmera, agravado por distância/ângulo/foco. É um efeito óptico conhecido de fotografar telas, não um bug de software.

Nenhum dos dois é causado pelo motor de OCR (`rapidocr-openvino`) nem seria corrigido trocando de motor — `../../studies/estudo-motores-ocr.md` já mediu os motores candidatos como empatados em acurácia sobre o gabarito formal; esta investigação, sobre capturas fora do gabarito, mostra que o texto que falha aqui está literalmente apagado ou distorcido na foto de entrada, antes de qualquer motor rodar.

## Como evitar / mitigar
Nenhuma mitigação de software aplicada ou recomendada como primeira ação. Ações físicas, na ordem de prioridade sugerida por esta investigação:

1. **Glare**: ajustar ângulo de câmera e/ou posição de fontes de luz para tirar o reflexo de cima do painel; considerar filtro polarizador na lente, que é a solução padrão para esse tipo de reflexo especular.
2. **Moiré**: aproximar-se do ótimo de foco/distância da câmera (ver `../d-specs/webcam-ugreen-4k.md`, que já documenta que resolução mais alta não é sempre melhor para esta câmera); avaliar se um leve desfoque controlado ou reamostragem reduz o padrão de interferência sem custar nitidez de texto — não testado nesta sessão.

Enquanto essas causas físicas não forem atacadas, ajustar thresholds do OCR ou trocar de motor não resolve: parte da informação está fisicamente ausente da foto (glare) ou embaralhada de forma não determinística entre frames da mesma tela (moiré), e ambos são problemas de captura, não de leitura.

**Mitigação parcial, agora medida (2026-08-14): a metade "moiré" é atacável por software; a metade "glare" não.** A observação `"Version"`/`"Versian"` acima motivou a votação multi-frame (`../f-specs/corroboracao-ocr-multi-frame.md`), e a validação ao vivo (`../../studies/estudo-votacao-ocr-multi-frame.md`) confirmou a hipótese: `ocr_votes=3` corrigiu **4 de 4** erros instáveis entre frames que a leitura única cometeu. O que ela **não** toca é a degradação estável — texto apagado por glare, ou cortado pela borda de rolagem (`texto-cortado-por-borda-de-rolagem-e-ilegivel.md`) — porque votar remove o que varia, nunca o que é idêntico em todos os frames. A ação física continua sendo a primeira ação para o glare; a votação não a substitui, e custa ~2x em tempo.

## Status
Aberto — 2026-08-14. Causas identificadas e ilustradas com casos concretos das 5 capturas de 2026-08-12. Nenhuma correção física aplicada; a câmera foi reposicionada depois (as capturas de 2026-08-14 têm bem menos glare, moiré ainda visível), e existe agora uma mitigação de software medida que cobre só a classe de erro instável (ver acima).
