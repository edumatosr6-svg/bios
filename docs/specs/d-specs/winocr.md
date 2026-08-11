# WinOCR (Windows.Media.Ocr)

## O que é
OCR nativo do Windows (API `Windows.Media.Ocr`), acessado via o pacote Python `winocr` 0.0.15 — sem nenhum modelo para baixar, usa o que já vem no sistema operacional.

## Por que essa e não outra
Integrado durante a busca pela meta de <8s por leitura (ver `../../studies/estudo-motores-ocr.md`) como o extremo de velocidade: **0.33s de leitura** num frame ao vivo 1280x720, ~14x mais rápido que o rapidocr e ~130x mais rápido que o paddleocr na mesma imagem. Zero dependência de download e zero custo de inicialização relevante.

Não é a escolha primária porque lê mal e porque a saída dele quebra o pipeline — ver Limitações.

## Como é usada aqui
`ocr.py`, classe `WinOCREngine`, atrás da interface comum `OCREngine`; criada via `create_ocr_engine("winocr")` e disponível nas flags `--engine` de `perception/run.py` e `gui.py` (ver `../f-specs/selecao-motor-ocr.md`).

## Limitações conhecidas

- **Acurácia de leitura ruim, medida (2026-08-10).** Contra o gabarito: **7/11 de texto** (os outros três motores fazem 11/11) e **0/2 e 0/1 nas duas fotos do AMI — simplesmente não consegue lê-las**; mais 5/11 de seleção, 0/4 em submenu e ~9 falsos positivos, incluindo 2 numa imagem que é negativo verdadeiro. Tabela completa em `../../studies/estudo-motores-ocr.md`. Isto é independente da geometria de linhas abaixo, e sozinho já o descarta como fonte primária.
- **Não reporta confiança por palavra** — limitação estrutural da API; o wrapper marca 100.0 fixo. Qualquer consumidor que filtre por confiança não filtra nada com este motor. Agrava o item acima: os ~9 falsos positivos não seriam filtráveis por confiança.
- **Geometria de linhas incompatível com o E5 do motor de percepção** — teto observado na prática em 2026-08-07, antes da medição de acurácia. Rodar `perception.run --summary` com `--engine winocr` sobre um frame real ao vivo produz 45 primitivas mas **1 grupo, 1 classe e 0 estados**, com abstenção `E5.grouping no_regular_arrangement_found`; na mesma imagem o `rapidocr-openvino` produz 56 primitivas → 3 regiões → 3 grupos → 5 classes → 1 estado correto ("Security" selected, conf 0.83).

  **Por que**: a API `Windows.Media.Ocr` segmenta linhas de forma diferente da linhagem PP-OCR sobre a qual o E5 foi calibrado — menos linhas no total (20 vs 31 no frame de teste), fusões e divisões diferentes, e inclusão de ícones no texto (leu "@ Setup" com o glifo do ícone). A detecção de arranjo regular do E5 depende do ritmo geométrico das linhas; com essa segmentação o ritmo não aparece e o estágio abstém. Não é bug do winocr nem do E5 isoladamente: é incompatibilidade entre a geometria que um produz e a que o outro espera. O sistema **abstém em vez de chutar** (0 estados, motivo nomeado), conforme `../../architecture/PERCEPTION_PIPELINE_SPEC.md` — o teto degrada para abstenção, não para erro silencioso.

  **Havia dois caminhos para destravá-lo**: (1) tornar o E5 tolerante à geometria dele (aceitar linhas fundidas e ícones embutidos na detecção de ritmo); (2) rebaixá-lo a canal simbólico auxiliar, nunca alimentando o E5. **A medição de acurácia elimina o caminho (1)**: mesmo com o E5 tolerando a geometria, a leitura não sustentaria o gabarito. Investir nele resolveria um problema para descobrir outro atrás dele. O teto continua real, mas deixou de ser o gargalo relevante — é o segundo obstáculo de uma fila, não o primeiro.

## Status
**Descartado como fonte simbólica primária — 2026-08-10**, agora com número e não só por observação. Continua instalado e alcançável por `--engine winocr`, e continua sendo de longe o mais rápido (0.33s). Antes dessa data o descarte se apoiava só na geometria de linhas que quebra o E5, teoricamente contornável; a validação de acurácia mostrou que o contorno não bastaria. O que sobra dele é o papel de canal simbólico auxiliar para usos que não dependam de acurácia de estado.

Feature afetada pelo teto do E5, enquanto ele for alcançável por flag: `../f-specs/motor-percepcao-interface.md` e `../f-specs/selecao-motor-ocr.md`.
