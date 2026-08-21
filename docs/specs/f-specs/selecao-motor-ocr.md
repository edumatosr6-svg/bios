# Seleção de motor de OCR

## Objetivo
Permitir escolher, por flag, qual motor de OCR alimenta a fonte simbólica do projeto — e comparar todos sobre a mesma imagem num comando só. Existe porque a meta de <8s por leitura exigiu integrar motores além do PaddleOCR (ver `../../studies/estudo-motores-ocr.md`), e trocar de motor não podia exigir tocar código dos consumidores: todos ficam atrás da interface comum `OCREngine` de `ocr.py`.

## Escopo
- **Dentro**: `ocr.py::create_ocr_engine` aceitando 4 nomes — `rapidocr-openvino`, `rapidocr-onnxruntime`, `winocr`, `tesseract` (eram 5; o `paddleocr` foi **removido em 2026-08-20**, ver `../d-specs/paddleocr.md`); a lista única `ocr.py::ENGINE_CHOICES` e o default único `ocr.py::DEFAULT_ENGINE`, consumidos por **todos** os pontos de entrada (`gui.py`, `perception/run.py`, `main.py`, `watcher.py`, `study_ocr_engines.py`) e também pelo nível de biblioteca (`perception.perceive()`/`default_pipeline()`, `perception/stages/e2_extraction.py`); `study_ocr_engines.py` (raiz) como comparador.
- **Fora**: comparar os motores entre si — isso é do estudo, não desta feature: velocidade e acurácia contra o gabarito em `../../studies/estudo-motores-ocr.md`.

## Comportamento esperado
- `create_ocr_engine(name)` devolve o engine pedido; nome desconhecido é erro. Os dois nomes `rapidocr-*` selecionam o backend de inferência (ONNX Runtime ou OpenVINO) do mesmo `RapidOCREngine`.
- `study_ocr_engines.py` roda todos os motores sobre a mesma imagem (`--speed`) e contra o gabarito (`--accuracy`), **cada motor em subprocesso isolado, sequencialmente — nunca concorrente**: motores CPU-bound competindo pelos mesmos cores distorceriam as medições. O isolamento também garante que crash de um motor não derruba os outros, e motor não instalado aparece como `UNAVAILABLE` na tabela em vez de quebrar o benchmark (é o caso do tesseract hoje — binário não instalado, instalação pendente de autorização do usuário).

- `ENGINE_CHOICES` / `DEFAULT_ENGINE` são o default do projeto: nome não passado, `DEFAULT_ENGINE` (hoje `rapidocr-openvino`). Vale igual na CLI e na biblioteca.

## Detalhes técnicos

**Lista e default centralizados em `ocr.py` (2026-08-07).** A lista de motores estava copiada em cinco chamadas de `argparse` diferentes. Não é hipótese: foi exatamente por isso que `main.py` e `watcher.py` ficaram para trás quando os motores novos entraram — versões anteriores desta F-spec chegaram a registrar essa omissão como escopo "Fora", ou seja, uma duplicação de literal virou uma limitação documentada do produto. Com `ENGINE_CHOICES` e `DEFAULT_ENGINE` importados de `ocr.py`, os cinco pontos de entrada mais o `study_ocr_engines.py` (que faz `ENGINES = ENGINE_CHOICES`) oferecem sempre o mesmo conjunto, e a próxima troca de motor é uma linha em vez de cinco.

O default foi centralizado junto, e **também vale no nível de biblioteca** — `perception.perceive()`, `default_pipeline()`, `Extraction.__init__`, `SymbolicSource.__init__` e `default_sources()` usam `DEFAULT_ENGINE`, não uma string literal. A razão: um default dividido (CLI dizendo `rapidocr` e `perceive()` dizendo `paddleocr`) seria armadilha para quem usa o motor de percepção como biblioteca, que veria um desempenho e um comportamento diferentes dos documentados sem ter pedido nada de diferente. Essa justificativa só existe aqui — o código tem a medição que justifica o valor de `DEFAULT_ENGINE` (`ocr.py`), mas não explica por que o nível de biblioteca segue o mesmo default.

Decisões por motor ficam nas D-specs: `../d-specs/rapidocr.md`, `../d-specs/paddleocr.md`, `../d-specs/winocr.md`. Destaques não óbvios: o rapidocr exige engine types como Enum (`rapidocr.utils.typings.EngineType` — string crua falha com "must be Enum Type"), roda com `Global.use_cls=False` e com `Global.log_level="warning"` (sem isso, um parágrafo de log de carga de modelo por leitura — tolerável ao escolher motor, ruído depois que ele virou default); o winocr não reporta confiança por palavra (wrapper fixa 100.0).

**Por que o comparador é um script só (2026-08-10).** Velocidade e acurácia eram dois scripts com nomes inconsistentes entre si e com a convenção `study_*` já existente no repositório (`study_selection_methods.py`, `study_temporal.py`). Viraram `study_ocr_engines.py` com `--speed`, `--accuracy` ou os dois por padrão — são as duas metades de uma pergunta só, e o estudo correspondente também é um só.

## Critérios de aceite
- `study_ocr_engines.py --speed` completa com todos os motores instalados medidos e os ausentes como `UNAVAILABLE`.
- Pipeline completo (`perception.run --summary`) com `--engine rapidocr-openvino` sobre frame ao vivo produz estado correto — verificado em 2026-08-07 ("Security" selected, conf 0.83; ver o estudo).
- Trocar de motor por flag muda o resultado de forma mensurável e previsível, sem tocar código de consumidor: verificado em 2026-08-10 rodando os 4 motores instalados sobre os mesmos 10 casos de gabarito através do pipeline completo (`../../studies/estudo-motores-ocr.md`). Esse exercício é hoje o teste mais forte que a feature tem — ele só é possível porque a lista e o default estão centralizados.
- Sem teste automatizado dedicado ainda — a validação é manual, via o script de estudo e o pipeline.

## Status
Concluída — 2026-08-07, atualizada em 2026-08-10 (validação de acurácia dos 4 motores instalados; comparador unificado em `study_ocr_engines.py`). Código em `ocr.py` (`ENGINE_CHOICES`, `DEFAULT_ENGINE`, `create_ocr_engine`), consumido por `gui.py`, `perception/run.py`, `main.py`, `watcher.py`, `study_ocr_engines.py`, `perception/__init__.py` e `perception/stages/e2_extraction.py`. Default do projeto: `rapidocr-openvino`.

## Questões em aberto
- ~~**Default trocado sem a validação de acurácia que o precederia.**~~ — **resolvido em 2026-08-10**: a comparação formal contra o gabarito foi feita e confirmou o default (`../../studies/estudo-motores-ocr.md`). A troca aconteceu antes da validação, mas a validação a sustentou. O cenário nomeado em que reverter seria o certo a fazer — entrada de bordas duras (HDMI/VM/screenshot) — **aconteceu de fato em 2026-08-20** e foi resolvido sem trocar de motor: a camada de tools lê o cursor pelo `selection.py` (`camada-de-tools-consulta-bios.md`). O `paddleocr` foi removido do projeto na mesma data, então **reverter não custa mais um flag** — custa reinstalar a dependência e desfazer commits (`../d-specs/paddleocr.md`).
- `--engine winocr` produz 0 estados no pipeline, e desde 2026-08-10 sabe-se que ajustar o E5 não bastaria: a acurácia de leitura dele o descarta de qualquer forma — `../d-specs/winocr.md`.
- Tesseract nunca entrou em nenhuma das duas comparações, velocidade ou acurácia — binário não instalado.
