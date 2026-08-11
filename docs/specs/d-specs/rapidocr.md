# RapidOCR

## O que é
Runtime de OCR que roda a mesma linhagem de modelos PP-OCR do PaddleOCR, mas via export ONNX próprio, sem depender do framework PaddlePaddle — com backend de inferência selecionável (ONNX Runtime ou OpenVINO).

## Por que essa e não outra
Adotada para atingir a meta explícita de **<8s por leitura**, inalcançável com PaddlePaddle nesta máquina (sem GPU NVIDIA, mkldnn quebrado — ver `../p-specs/paddleocr-cpu-lento-sem-mkldnn.md`). Alternativas consideradas:

- **Backends acelerados do próprio ecossistema Paddle (paddlex, plugin HPI)** — descartado com evidência: não instala em Windows nativo (falta wheel de `ultra-infer-python`; a doc do PaddleX manda usar WSL/Docker, e o usuário decidiu explicitamente não ir para WSL por ora). Erro literal na P-spec acima.
- **DirectML (`onnxruntime-directml`) na iGPU Iris Xe** — não tentado: bugs conhecidos de inferência incorreta em Iris Xe.
- **WinOCR** — muito mais rápido ainda, mas lê pior e a geometria de linhas dele quebra o E5 do pipeline (ver `winocr.md`).

O que decidiu por RapidOCR: **pip puro com wheel Windows nativo** (nenhum toolchain, nenhum container), roda os mesmos modelos PP-OCR (o que maximiza a chance de acurácia equivalente ao paddleocr atual), e funciona em Python 3.13 apesar de a doc oficial dizer suporte <3.13 — verificado nesta máquina.

## Como é usada aqui
`ocr.py`, classe `RapidOCREngine`, atrás da interface comum `OCREngine`. Criada via `create_ocr_engine("rapidocr-onnxruntime")` ou `create_ocr_engine("rapidocr-openvino")` — mesmos nomes aceitos pelas flags `--engine` de todos os pontos de entrada (ver `../f-specs/selecao-motor-ocr.md`).

**`rapidocr-openvino` é o default do projeto desde 2026-08-07** (`ocr.py::DEFAULT_ENGINE`), tanto nas CLIs quanto no nível de biblioteca (`perception.perceive()`, `perception/stages/e2_extraction.py`). Ou seja: é ele que roda quando ninguém passa `--engine`.

Versões: `rapidocr` 3.9.2; backends `onnxruntime` 1.28.0 e `openvino` 2026.3.0 (todos via pip).

Configuração relevante:
- `Det.lang_type=EN` / `Rec.lang_type=EN` — BIOS é texto em inglês.
- `Global.use_cls=False` — classificador de rotação 180° desligado; foto de tela é sempre de pé, a etapa só custaria tempo.
- Engine types passados como Enum (`rapidocr.utils.typings.EngineType`) — passar string crua falha com "must be Enum Type".
- `Global.log_level="warning"` — sem isso o RapidOCR imprime a cada leitura um parágrafo dizendo quais arquivos de modelo carregou. Era tolerável enquanto ele era um motor entre outros sendo avaliado; virou ruído quando passou a ser o default e a rodar em toda captura.
- Modelos: `PP-OCRv6_det_small.onnx` / `PP-OCRv6_rec_small.onnx`, baixados automaticamente no primeiro uso.

Número-chave: **4.53s de leitura quente** (openvino) num frame ao vivo 1280x720, contra 7.69s do backend onnxruntime e 37-44s do paddleocr. Tabelas completas e metodologia em `../../studies/estudo-motores-ocr.md`.

**Escolha de backend fechada (2026-08-10).** A validação de acurácia mostrou que `openvino` e `onnxruntime` produzem resultado **idêntico, linha por linha**, em todos os casos do gabarito. Não há trade-off de qualidade a ponderar entre os dois: preferir OpenVINO se justifica **só** por velocidade.

## Limitações conhecidas
- **Perde para o paddleocr em exatamente 1 caso do gabarito, e ele é sintético.** A caixa de detecção do item selecionado engole a barra de destaque quando as bordas dela são duras; em foto de câmera, cujas bordas são suaves, isso não acontece. A contaminação chega aos descritores do E3 e ao agrupamento do E6, e o motor abstém. **É um risco latente, não um defeito atual**: ele ativa se o projeto ganhar uma fonte de entrada de bordas duras (HDMI, VM, screenshot). Medições, cadeia de falha e a correção tentada e rejeitada: `../p-specs/caixa-de-deteccao-engloba-barra-de-destaque.md`.
- Download dos modelos ONNX no primeiro uso — a primeira execução precisa de rede.
- Doc oficial declara Python <3.13; funciona em 3.13 aqui, mas é compatibilidade não prometida upstream — risco em upgrades futuros do pacote.

## Status
Em uso, **como default do projeto** (`rapidocr-openvino`) — 2026-08-07, revisado em 2026-08-10. Único motor integrado que atinge a meta <8s por leitura sem quebrar o pipeline.

**A validação formal de acurácia contra o gabarito foi feita em 2026-08-10** e **confirmou a escolha**: a suspeita que a bloqueava — modelos `small` lendo pior que os do paddleocr — não se confirmou, os dois empatam em **11/11 de texto**. O default deixa de ser risco assumido às cegas e vira risco medido e delimitado. Placar completo e veredito em `../../studies/estudo-motores-ocr.md`; reverter continua custando um flag (`--engine paddleocr`).

Ressalva que permanece: o gabarito contra o qual isso foi medido está reduzido (a varredura de ~240 negativas não existe mais; 1 fixture AMI ausente), então o "0 falsos positivos" é um número fraco — ver `../p-specs/fixture-de-teste-nunca-versionada.md`.
