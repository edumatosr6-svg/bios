# PaddleOCR

## O que é
Motor de OCR baseado em deep learning (família de modelos PP-OCR, sobre o framework PaddlePaddle) usado para ler texto de fotos/capturas de tela de BIOS — fica atrás da interface comum `OCREngine` em `ocr.py`, ao lado do `TesseractOCR` (motor clássico baseado em Tesseract).

## Por que essa e não outra
Tesseract foi o motor original do protótipo, escolhido por ser mais simples de instalar. PaddleOCR foi adotado depois por ser, nas palavras do docstring de `PaddleOCREngine`, "noticeably more accurate than Tesseract on real screen photos (varied lighting/angle)" — mantendo o mesmo schema de saída (bloco/linha/palavra + bbox + confiança), o que permitiu trocar de engine sem alterar `main.py` nem os consumidores da saída. Desde 2026-08-07, `create_ocr_engine(name)` oferece cinco motores (`rapidocr-openvino`, `rapidocr-onnxruntime`, `paddleocr`, `winocr`, `tesseract` — ver `../f-specs/selecao-motor-ocr.md`), e **PaddleOCR deixou de ser o default no mesmo dia**: `ocr.py::DEFAULT_ENGINE` é `rapidocr-openvino`, em todos os pontos de entrada e também no nível de biblioteca (`perception.perceive()`, `perception/stages/e2_extraction.py`). PaddleOCR continua integrado e a um flag de distância (`--engine paddleocr`), mas não é mais o que roda por omissão — ver `rapidocr.md` e "Status" abaixo.

Trade-off pago por essa escolha: PaddleOCR é muito mais caro de inicializar e rodar em CPU do que Tesseract — ver "Limitações conhecidas".

## Como é usada aqui
`ocr.py`, classe `PaddleOCREngine`, envolve `paddleocr.PaddleOCR`. Alcançável por `--engine paddleocr` (ou `create_ocr_engine("paddleocr")`) a partir de dois caminhos:
- Caminho legado — `main.py`/`watcher.py`, ver `../../reference/PROCESSO_OCR.md` (etapa 3, "OCR (PaddleOCR)"). O texto daquela referência descreve o caminho quando PaddleOCR era o default.
- Motor novo — `perception/stages/e2_extraction.py`, que importa `create_ocr_engine` de `ocr.py` para a fonte simbólica de primitivas (ver `../f-specs/motor-percepcao-interface.md`). O default dessa fonte é `DEFAULT_ENGINE`, hoje `rapidocr-openvino`; PaddleOCR só entra se explicitamente pedido.

Configuração atual (`PaddleOCREngine.__init__`, `lang="en"`):
- `use_doc_orientation_classify=False`, `use_doc_unwarping=False`, `use_textline_orientation=False` — desligadas porque o pipeline lê fotos de tela plana e vertical, não documentos escaneados; essas etapas de pré-processamento não se aplicam aqui e só custam tempo.
- `enable_mkldnn=False` — workaround obrigatório para um crash do PaddlePaddle 3.3.1, não uma escolha de performance. Ver `../p-specs/paddleocr-cpu-lento-sem-mkldnn.md`.
- `ocr_version="PP-OCRv4"` — fixado nesta sessão (2026-08-07), ver abaixo.

**`ocr_version="PP-OCRv4"` fixado explicitamente**, no lugar do default implícito do PaddleOCR para `lang="en"`, que é o par PP-OCRv6 "medium" (det+rec). Sem mkldnn esse default é inviável — medido nesta máquina (Windows, 12 núcleos, sem GPU):

| Configuração | Construção do engine | Leitura completa (`predict()`, captura real 1280x720) |
|---|---|---|
| PP-OCRv6 medium (default implícito) + mkldnn=False | >7min, não terminou (processo morto em 7min14s) | não medido — nunca terminou a construção |
| PP-OCRv4 mobile + mkldnn=False (config atual) | ~2.4-9.4s (cache quente vs. frio) | ~30-31s |

Pipeline `perceive()` completo (11 estágios E0-E10) com PP-OCRv4: 31.87s no total — as outras 10 fases (E1, E3-E9) juntas custam menos de 1s, ou seja, o OCR é hoje praticamente 100% do tempo de execução do motor de percepção (ver `../f-specs/motor-percepcao-interface.md`, "Detalhes técnicos"). Verificação de ponta a ponta depois da mudança: `py -3.13 -m perception.run --source file --input captures/20260806-144020_auto.png --summary --trace` rodou sem nenhum monkeypatch, exit code 0, encontrando corretamente "System Information" e o relógio "14:17:06" como itens selecionados/destacados, com abstenções nos moldes já esperados pela F-spec.

## Limitações conhecidas
- **Sem mkldnn, o custo do executor CPU escala mal com o tamanho do modelo** — teto de desempenho real, contornado pela repinagem de versão acima, não eliminado. Causa raiz (bug de oneDNN/PIR no PaddlePaddle 3.3.1, confirmado independente de modelo) e números completos em `../p-specs/paddleocr-cpu-lento-sem-mkldnn.md`.
- **Não atinge a meta de <8s por leitura nesta máquina, e a aceleração do próprio ecossistema não está disponível em Windows nativo.** Fica em **37-44s de leitura** (fixture e frame ao vivo), contra 2.77-4.53s do `rapidocr-openvino` lendo essencialmente as mesmas linhas — medições em `../../studies/estudo-motores-ocr.md`. O plugin HPI do paddlex não instala em Windows nativo (falta wheel de `ultra-infer-python`); erro literal e alternativas fechadas na P-spec acima.
- **Acurácia do PP-OCRv4 (par "mobile") validada em 2026-08-10 — e ele continua sendo o melhor do projeto em seleção fim a fim.** PP-OCRv4 é uma geração mais antiga e menor que o PP-OCRv6 "medium" que era o default implícito antes desta repinagem, e a troca de velocidade por acurácia tinha ficado sem comparação formal. Ela foi feita: **9/11 de seleção**, o melhor placar entre os 4 motores instalados, com o texto empatado em 11/11 — ou seja, a repinagem está validada em acurácia, não só em velocidade. O contraponto é **1 falso positivo** (`Save Options`, contra 0 do rapidocr) e o tempo de leitura acima. Tabelas em `../../studies/estudo-motores-ocr.md`.
- **Downscale da imagem de entrada: medido, não aplicado.** As fixtures `captures/positivo_*.jpg` (5 fotos reais da Positivo usadas na metodologia de comparação da F-spec) são 3840x2160 (4K) — 9x mais pixels que uma captura ao vivo da webcam configurada no projeto (1280x720, ver `webcam-ugreen-4k.md`). OCR direto nelas: 54.19s. Redimensionando para largura 1280 antes do OCR: 25.12s — quase metade do tempo, com o mesmo número de linhas encontradas (32 em ambos os casos) nessa amostra, sem perda de acurácia aparente. Mesmo espírito do achado "resolução mais alta nem sempre é melhor" de `webcam-ugreen-4k.md`, mas um achado distinto — ali é sobre a nitidez nativa da câmera, aqui é sobre o tamanho da imagem que o OCR recebe. Não implementado porque tocaria o contrato de superfície canônica que `../../architecture/PERCEPTION_PIPELINE_SPEC.md` e `../../architecture/VISUAL_FEATURE_SPEC.md` regem explicitamente — falta decidir onde cortar resolução (dentro de `PaddleOCREngine.read()`, só para OCR, ou no estágio E1 Condicionamento, para a pipeline inteira), e essa decisão merece ser deliberada, não ser efeito colateral de uma correção de performance. Registrado aqui como opção medida e não descartada.

## Status

**REMOVIDO do projeto — 2026-08-20.** Decisão explícita do usuário ("nunca mais vamos usar o paddle"), tomada depois de medir ao vivo o que custava mantê-lo como saída de emergência: numa tela real por HDMI, a mesma tool levou **63.5s** com `--engine paddleocr` contra **~5s** com o default. Removidos: a classe `PaddleOCREngine` (`ocr.py`), a entrada em `ENGINE_CHOICES`, o ramo em `create_ocr_engine`, e `paddlepaddle`/`paddleocr` do `requirements.txt`. Os arquivos que o usavam por omissão (`test_selection.py`, `test_perception.py`, `study_selection_methods.py`, `study_temporal.py`) foram repontados para `ocr.py::DEFAULT_ENGINE`.

**O que isso custa, explicitamente:**
- **A saída de emergência descrita abaixo deixou de existir.** O cenário "entrada de bordas duras (HDMI/VM/screenshot)" é real e foi confirmado ao vivo — mas foi resolvido por outro caminho, sem PaddleOCR: a camada de tools passou a ler o cursor pelo `selection.py` em vez dos canais do E7 (ver `../f-specs/camada-de-tools-consulta-bios.md`, "Cursor pelo caminho legado"), o que mantém o motor rápido **e** enxerga o destaque.
- **O projeto perdeu seu motor de referência de acurácia.** Os números do gabarito em `../../studies/estudo-motores-ocr.md` foram medidos com ele e continuam válidos como registro histórico, mas não são mais reproduzíveis num checkout limpo.
- Reinstalar é `pip install paddlepaddle paddleocr` e reverter estes commits; o histórico deste arquivo tem toda a configuração que funcionava.

**Isto toca arquivos que o Carlos Eduardo mantém** (`ocr.py`, `test_perception.py`) e remove um motor que ele documentou — vale avisá-lo.

### Histórico: substituído como default — 2026-08-07 (registro corrigido em 2026-08-10) Continua em uso opcional, atrás de `--engine paddleocr`, e continua sendo o motor de referência de acurácia do projeto; deixou de ser o que roda por omissão. Substituto: `rapidocr-openvino` (ver `rapidocr.md`), que roda a mesma linhagem de modelos e atinge a meta de <8s por leitura, inalcançável aqui pelo PaddlePaddle mesmo com `ocr_version="PP-OCRv4"` fixado para contornar `../p-specs/paddleocr-cpu-lento-sem-mkldnn.md` (37-44s de leitura).

A troca foi decisão explícita do usuário para uso na câmera e aconteceu **antes** da validação formal de acurácia; a validação veio depois e o resultado é mais interessante que "perdeu" — o PaddleOCR ganha em seleção fim a fim e perde em falso positivo, mas está 5-10x acima do requisito de tempo e por isso não disputa o posto de default (números e cronologia em `../../studies/estudo-motores-ocr.md`). Continua sendo o motor de referência de acurácia do projeto, agora com número que sustenta esse papel. Manter o PaddleOCR integrado é o que tornou essa validação possível, e é o que dá um caminho de volta de um flag.

**Cenário em que ele volta a ser preferido:** entrada de imagem com bordas duras (captura HDMI, VM, screenshot direto). O único caso do gabarito em que o rapidocr perde é exatamente esse, e o PaddleOCR não sofre dele — ver `../p-specs/caixa-de-deteccao-engloba-barra-de-destaque.md`.

Revisitar também se uma versão futura do PaddlePaddle corrigir o crash de oneDNN/PIR — nesse caso a comparação de velocidade muda de premissa, e com a acurácia já medida a decisão seria direta.
