# Corroboração de OCR por votação multi-frame (`ocr_votes`)

## Objetivo
Reduz o efeito do ruído de frame a frame (moiré, jitter de sensor) sobre a leitura de texto, sem confiar numa leitura só. Nasce diretamente da investigação de 2026-08-14 sobre erros de leitura em captura ao vivo: a mesma frase saiu `"Version"` certa numa captura e `"Versian"` errada em outra, minutos depois, da mesma tela parada — evidência de que boa parte dos erros de caractere pontuais é ruído instável entre frames, não erro sistemático do motor de OCR (`../p-specs/glare-moire-degradam-ocr-captura-ao-vivo.md`, `../../studies/estudo-motores-ocr.md` §"Continuação"). A ideia, proposta pelo usuário: em vez de ler uma vez, tirar várias capturas do mesmo estado de tela parado e votar por região no que aparece com mais frequência.

Implementa, pela primeira vez para OCR, uma regra que já existia só como princípio não cumprido: §4 de `../../architecture/PERCEPTION_PIPELINE_SPEC.md` ("evidência temporal é sempre corroborante, nunca necessária... eleva confiança; sua ausência não a zera") e o docstring pré-existente de `perceive()` em `perception/__init__.py`, que já falava em frames extra só elevando confiança sem que isso tivesse sido implementado para o OCR até agora.

## Escopo
- **Dentro**: re-leitura de conteúdo de caixas já detectadas, a partir dos frames extras de um `FrameBundle`, com votação por maioria de texto exato e elevação de confiança proporcional à concordância.
- **Fora**: qualquer alteração na detecção geométrica (onde as caixas estão). A votação nunca adiciona, move ou remove uma caixa — só confirma ou corrige o conteúdo de uma caixa que a leitura primária já encontrou.

## Comportamento esperado
- `SymbolicSource(engine, votes: int = 1)`: com `votes == 1`, comportamento idêntico ao anterior (nenhuma mudança de caminho).
- Com `votes > 1`: a leitura primária roda sobre `surface.image` (o frame representante, `bundle.frames[-1]`) e decide a geometria de todas as caixas, como sempre. Em seguida, `SymbolicSource._corroborate` pega até `votes - 1` frames extras do bundle (excluindo o representante, mais recentes primeiro), roda uma leitura OCR **completa** em cada um (mesma chamada já paga na leitura principal — não um recorte por caixa), e casa cada linha lida nesses frames extras com a caixa mais próxima da leitura primária por sobreposição geométrica (IoU >= `MIN_MATCH_IOU = 0.5`).
- Por caixa, os textos (primário + matches dos frames extras) entram num `collections.Counter`; o texto majoritário vence. Se há concordância além da leitura primária (`winner_count > 1`), a confiança sobe proporcionalmente à fração de votos concordantes: `confidence += (1 - confidence) * agreement`, nunca ultrapassando 1.0. Discordância nunca derruba a confiança abaixo da leitura primária — "extra frames only raise confidence" (§4).
- **Casos de borda / abstenção graciosa**: corroboração é pulada e a leitura primária é devolvida sem tocar quando: não há `bundle`; o bundle só tem 1 frame; ou `surface.rectified` é `True` (pixels da superfície retificada são um warp só do frame representante, não compartilhados pelos outros frames — casar por IoU pixel a pixel deixaria de fazer sentido). Hoje essa terceira condição nunca dispara na prática, porque a retificação em E1 nunca funciona com o enquadramento de câmera atual (`../p-specs/retificacao-e1-inatingivel-sem-moldura-visivel.md`) — o que é justamente o que torna a corroboração alcançável agora.
- `default_pipeline()` / `perceive()` ganharam `ocr_votes: int = 1`, repassado até `Extraction` → `SymbolicSource`. `ocr_votes=1` é o comportamento de hoje, sem mudança nenhuma. `ocr_votes > 1` relê cada caixa a partir de até `ocr_votes - 1` frames extras do bundle; se `len(frames) < ocr_votes`, degrada graciosamente para o número de frames disponíveis em vez de falhar.
- CLI: `perception/run.py --ocr-votes N` (default 1), documentada em `--help`. Uso: `py -3.13 -m perception.run --source camera --frames 5 --ocr-votes 3 --summary` — `--frames` controla o tamanho do burst capturado da câmera, `--ocr-votes` controla quantos desses frames entram na votação.

## Detalhes técnicos
- **Por que reler o frame inteiro em vez de recortar cada caixa**: a primeira versão implementada recortava a caixa de cada primitivo e rodava OCR só no recorte, por frame extra. Medido sobre a captura real de 48 primitivos (`captures/20260812-160027_auto.png`): **132s para `ocr_votes=3` contra 16.6s de `ocr_votes=1`**, quase 8x mais lento, porque o overhead fixo por chamada do RapidOCR se multiplica pelo número de caixas (48 caixas × 2 frames extras = 96 chamadas pequenas). Reescrito para ler cada frame extra inteiro — a mesma chamada que a leitura principal já paga — e casar por IoU. Isso mantém o número de chamadas extras em `votes - 1`, independente da contagem de caixas, em vez de `votes × caixas`.
- **Por que casar por IoU e não reabrir a detecção**: casar detecções geométricas independentes entre execuções diferentes é o problema difícil (quantas caixas existem pode divergir entre leituras). A escolha de ter uma única passada de detecção (o frame representante) e usar os frames extras só para revotar *conteúdo* de caixas já existentes sidesteps esse problema por construção — não há nada para casar em termos de geometria, só de texto dentro de uma geometria fixa.
- **Peso da votação não calibrado**: a fórmula de elevação de confiança (`agreement = winner_count / len(texts)`) é uma primeira passagem não medida contra corpus real. A validação ao vivo de 2026-08-14 mediu **acerto de texto** (a string certa saiu ou não), não se a *curva de confiança* resultante está bem calibrada — isso continua não medido (ver "Questões em aberto").
- **`ocr_votes=3` é o ponto ideal medido, não um chute**: `votes=5` empatou com `votes=3` em acurácia e custou ~45% a mais de tempo. Ver "Validação de acurácia" abaixo.

## Validação de acurácia ao vivo (2026-08-14)
Medição completa, metodologia e ressalvas em `../../studies/estudo-votacao-ocr-multi-frame.md`. Resumo: 10 rodadas sobre uma BIOS Positivo (aba Main rolada), gabarito de 32 strings, **as duas configurações rodando sobre exatamente a mesma rajada de 5 frames** em cada rodada — capturar rajadas separadas mediria também o ruído entre momentos diferentes da câmera, que é justamente o que a votação ataca.

| Configuração | Bruto (320 alvos) | Contra o teto atingível (310) | Rodadas no teto | Tempo médio |
|---|---|---|---|---|
| `ocr_votes=1` | 306/320 (95.6%) | 306/310 | 6 de 10 | **5.9s** |
| `ocr_votes=3` | 310/320 (96.9%) | **310/310 (100%)** | **10 de 10** | 11.3s |

O placar bruto engana: um dos 32 alvos (`"Range of Years may vary."`) é **estruturalmente ilegível** — a linha está cortada pela borda de rolagem do painel, sem a metade superior das letras — e falhou 10/10 nas **duas** configurações. É degradação estável, não ruído, e nenhuma votação corrige (`../p-specs/texto-cortado-por-borda-de-rolagem-e-ilegivel.md`). Descontado ele, o teto é 310, e a leitura correta é: **a votação bateu o teto em todas as rodadas; a leitura única saiu com ao menos um erro em 40% das capturas.**

Os 4 erros da leitura única foram corrigidos pela votação, **4 de 4, nenhum sobrou**: `7.2.4.XD22CPG7.I219V.P` (rodadas 2 e 8) e `EC Build Date (MM/DD/YYYY)` (rodadas 4 e 9) — nunca o mesmo erro em duas rodadas seguidas, exatamente a assinatura de ruído instável entre frames que motivou a feature.

Ressalvas que não podem sair do lado do número: (a) **~2x mais lento, estourando a meta de <8s** do projeto — ver "Questões em aberto"; (b) amostra de **uma única tela e um único enquadramento**, com n=3 tendo sido insuficiente (diferença de 1 caso, dentro do ruído) e n=10 necessário para o resultado se separar; (c) as condições desta medição eram **melhores** que as das capturas de 2026-08-12 (câmera reposicionada, bem menos glare, moiré ainda visível) — havia menos ruído disponível para a votação corrigir, então é *plausível* que o ganho seja maior sob condições piores, mas isso **não foi medido**.

## Medições de tempo (pontuais, anteriores à validação)
Smoke test ad-hoc sobre `captures/20260812-160027_auto.png` (mesma imagem das duas P-specs de captura ao vivo), não um benchmark reprodutível como os de `../../studies/estudo-motores-ocr.md`:
- `ocr_votes=1`: ~11s (inclui construir o engine `rapidocr-openvino`).
- `ocr_votes=3` com 3 frames idênticos: ~12s — custo incremental por voto extra baixo, ~0.5-1s/voto, porque cada voto extra é uma leitura completa do frame (chamada já paga hoje), não uma leitura por caixa.
- Caminho descartado (recorte por caixa): ver "Detalhes técnicos" acima — 132s vs 16.6s.

**Esse "~0.5-1s por voto extra" não se sustentou ao vivo.** A validação de 2026-08-14 mediu 5.9s → 11.3s de `votes=1` para `votes=3`, ou seja ~2.7s por voto extra — próximo do custo de uma leitura completa de frame, que é o que cada voto extra de fato é. A estimativa otimista do smoke test vinha de 3 frames **idênticos** e de um total dominado pela construção do engine; o número de referência para decidir default é o da validação ao vivo, não este.

## Limitações conhecidas

**1. Degradação estável é invisível para a votação, por construção.** Votar entre frames remove o que varia; o que está errado de forma idêntica em todos os frames passa intacto. Vale para texto cortado pela borda de rolagem do painel (`../p-specs/texto-cortado-por-borda-de-rolagem-e-ilegivel.md`, confirmado 10/10 na validação) e para glare que apaga texto (`../p-specs/glare-moire-degradam-ocr-captura-ao-vivo.md`). A votação ataca ruído, não ausência de informação.

**2. A votação não protege a detecção.**
A votação só protege o *conteúdo* de uma caixa já detectada — não protege a detecção em si. Se o **frame representante** (`bundle.frames[-1]`, o único que passa pela detecção) for o frame ruim, a votação não ajuda em nada, porque a detecção já falhou antes da votação entrar em cena. Testado deliberadamente: `frames=[img_bom, img_bom, img_borrado]` (o borrado é o representante) — detecção caiu de 48 primitivos para 2. `frames=[img_borrado, img_bom, img_bom]` (o borrado é um extra, não o representante) — resultado idêntico ao de um frame só, confirmando que um frame degradado *entre os extras* não corrompe nada. Essa assimetria (o `-1` de "último do burst" decide tudo) não foi corrigida — ver `../p-specs/votacao-ocr-nao-protege-deteccao-do-frame-representante.md`.

## Critérios de aceite
- Lógico, validado por teste ad-hoc (não automatizado ainda): `ocr_votes=1` não muda nada em relação ao comportamento anterior ao commit; `ocr_votes>1` com frames idênticos não regride confiança; `ocr_votes>1` com um frame extra degradado não corrompe o resultado da leitura primária boa.
- Ainda não existe teste automatizado equivalente (nem `test_perception.py` cobre isso hoje — a lacuna de suíte automatizada já é uma questão em aberto conhecida de `motor-percepcao-interface.md`).
- ~~Falta validação de acurácia em captura ao vivo real~~ — **feita em 2026-08-14**, sem esperar o reenquadramento de câmera: `ocr_votes=3` acertou 100% do teto atingível em 10 de 10 rodadas e corrigiu 4 de 4 erros da leitura única. Ver "Validação de acurácia ao vivo" acima e `../../studies/estudo-votacao-ocr-multi-frame.md`. Continua não reprodutível a partir de um clone (script ad-hoc não versionado).

## Status
Implementada, testada logicamente e **validada em acurácia ao vivo** — 2026-08-14. Código em `perception/stages/e2_extraction.py` (`Extraction.__init__`, `SymbolicSource.__init__`/`_corroborate`), `perception/__init__.py` (`ocr_votes` em `default_pipeline()`/`perceive()`), `perception/run.py` (`--ocr-votes`).

**O default não mudou**: `ocr_votes=1` continua o padrão no código. A validação mostrou que `ocr_votes=3` lê melhor, mas ao custo de ~2x no tempo (5.9s → 11.3s), o que estoura a meta de <8s por leitura do projeto. Adotar 3 como default é uma decisão em aberto e consciente sobre esse requisito, não uma consequência automática da medição.

## Questões em aberto
- **Adotar `ocr_votes=3` como default é uma decisão de produto ainda não tomada.** Acurácia diz "sim" (100% do teto, 10/10 rodadas); tempo diz "não" (11.3s contra a meta de <8s estabelecida em `../../studies/estudo-motores-ocr.md`, que foi a razão de o motor de OCR ter sido trocado). Quem decidir precisa escolher explicitamente entre precisão e tempo de resposta, ou reduzir o custo por voto antes.
- Detecção do frame representante não escolhe o frame mais nítido — sempre usa o último do burst (`bundle.frames[-1]`). Se ele for o frame ruim, a votação não ajuda. Ver `../p-specs/votacao-ocr-nao-protege-deteccao-do-frame-representante.md`.
- **Ganho sob condições piores não foi medido.** A validação rodou com a câmera reposicionada e bem menos glare que as capturas de 2026-08-12; é plausível, mas não estabelecido, que a votação ganhe mais quando há mais ruído a corrigir.
- **Generalização não medida**: uma única tela de BIOS (Positivo, Main rolada), um enquadramento. Nada diz ainda como o ganho se comporta em outros modelos/telas.
- Peso de votação (`agreement`) não calibrado contra dado real — a validação mediu acerto de texto, não se a curva de confiança resultante está bem calibrada.
