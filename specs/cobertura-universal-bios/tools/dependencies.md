# Dependências — cobertura-universal-bios

## Regra

Este slug **não adiciona nenhuma dependência de terceiros**. Tudo que ele precisa já
está em `requirements.txt` ou na biblioteca padrão. Adicionar uma dependência aqui
seria um sinal de que a spec derivou do escopo — o slug é composição do que já existe.

## Já presentes e efetivamente usados

| Dependência | Versão em `requirements.txt` | Por que este slug precisa |
|---|---|---|
| `opencv-python` | `>=4.9` | Captura de frame e o teste de estabilidade (`absdiff`) que `BiosSession.wait_stable` usa antes de cada leitura pós-tecla (R5). |
| `rapidocr` | `==3.9.2` | Motor de OCR padrão do pipeline de percepção; F1/F2/F3 leem por ele. Pinado — não mexer neste slug. |
| `onnxruntime` | `==1.28.0` | Backend do `rapidocr`. |
| `openvino` | `==2026.3.0` | Backend alternativo/NPU. Não é requisito deste slug, mas não pode ser quebrado por ele. |
| `pyserial` | `>=3.5` | `BiosActuator` — envio das teclas de navegação. Só teclas de `SAFE_KEYS` (R1). |
| `pytesseract` / `Pillow` | `>=0.3.10` / `>=10.0` | Caminho de OCR legado usado por `session.read_cursor`, que `study_scroll_map.py` já usa para mapear a rolagem. |

## Biblioteca padrão

| Módulo | Uso |
|---|---|
| `json` | Ler/escrever `data/label_index.json` (F3). |
| `dataclasses` | `PageScan`, `ScreenSlice`, entradas do índice — mesmo estilo de `registry.py`. |
| `argparse` | CLI do estudo de tour (`study_label_index.py`), como os demais estudos. |
| `time` | Cronometragem do KPI K4. |
| `pathlib` | Caminho fixo do índice. |

## Módulos internos reutilizados (não reimplementar)

| Módulo | O que este slug usa |
|---|---|
| `biostools/registry.py` | `Tool`, `Step`, `ToolResult`, `AllFields`, `SAFE_KEYS`, `UnsafeRoute`, `register`, `all_tools`. |
| `biostools/navigate.py` | `enter_main_menu_screen`, `TOP_LEVEL_SCREENS`, `SIDEBAR_MAX_X`, `move_to`, `activate`, `looks_like_dialog`. |
| `biostools/labels.py` | `field()`, `screen()`, `FIELDS`, `SCREENS`, `UnknownLabel`, e a disciplina de provenance. |
| `biostools/screen.py` | `match_score`, `field_value`, `field_pairs`, `screen_id`, `selection_abstentions`, `nav_element_ids`. |
| `biostools/session.py` | `BiosSession`, `read_stable`, `press` — recebida por parâmetro, nunca instanciada nos módulos novos (R4). |
| `study_scroll_map.py` | `content_lines`, `stable_signature`, `scan_page`, `scroll_to_screen`, `find_in_map` — mecânica já provada ao vivo; F1 deve consolidá-la em `biostools/`, não duplicá-la. |
| `study_menu_tour.py` | Padrão de tour pelas telas de topo e a exclusão de `save_and_exit`. |

## Artefato de dados novo

| Caminho | Formato | Produzido por | Regime |
|---|---|---|---|
| `data/raw_labels/<screen>.json` | JSON (linhas cruas) | F0 (`--harvest`) | **Commitado.** Evidência das grafias CONFIRMADO (K12). |
| `data/label_index.json` | JSON (cabeçalho + `pages` + `entries`) | F3 (tour) | **Commitado no git.** Não pode cair em `.gitignore`. Ver `docs/specs/p-specs/fixture-de-teste-nunca-versionada.md`. |
| `specs/cobertura-universal-bios/question-bank.md` | Markdown tabelado | F5 (parcialmente **humano** — CA-F5.3) | Commitado; instrumento de medição de K1–K4. |

Edição **humana** exigida, não automatizável (CA-F0.3): `biostools/labels.py`
(`SCREENS` + o novo `SUBMENUS`), preenchida a partir de `data/raw_labels/` com
revisão por olho humano antes de qualquer marca CONFIRMADO.

## Hardware

| Item | Requisito |
|---|---|
| Máquina alvo | Positivo, BIOS 2.22.0058 (único modelo em escopo). |
| Câmera | A já configurada em `capture.open_camera`. |
| Cabo/atuador | Serial (`--serial-port COM3` nos estudos existentes). |

Todos os testes exceto os marcados `[BANCADA]` rodam **sem** câmera e **sem** cabo.
