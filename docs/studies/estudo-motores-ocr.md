# Estudo: qual motor de OCR usar — velocidade e acurácia

Datas: metade de **velocidade** em 2026-08-07; metade de **acurácia** em 2026-08-10.

## Pergunta

O motor de percepção estava inutilizável em uso interativo por causa do OCR: 30-50s por leitura com PaddleOCR em CPU, contra <1s de todas as outras 10 etapas do pipeline juntas (ver `../specs/p-specs/paddleocr-cpu-lento-sem-mkldnn.md`). Daí a meta explícita: **menos de 8 segundos por leitura**.

A decisão tem duas metades, medidas com três dias de distância e reunidas aqui porque são a mesma pergunta:

1. **Algum motor atinge a meta nesta máquina, e o pipeline continua funcionando com ele?** (velocidade, 2026-08-07)
2. **O rápido lê tão bem quanto o lento?** (acurácia contra o gabarito, 2026-08-10)

A suspeita concreta que a metade 2 precisava derrubar: o `rapidocr` roda os modelos PP-OCR **small** (`PP-OCRv6_det_small` / `PP-OCRv6_rec_small`), menores que o PP-OCRv4 mobile do paddleocr — modelo menor poderia ler pior. **Não se confirmou.**

## Ambiente

- CPU: Intel i5-1235U (12ª geração, 10 cores físicos), **sem GPU NVIDIA**; iGPU Iris Xe integrada.
- Windows nativo (sem WSL — decisão explícita do usuário, ver "Caminhos descartados").
- Câmera ao vivo: UGREEN 4K a 1280x720 (ver `../specs/d-specs/webcam-ugreen-4k.md`).

## Metodologia

Tudo roda por `study_ocr_engines.py` (raiz do projeto), que faz as duas metades:

```
py -3.13 study_ocr_engines.py            # as duas
py -3.13 study_ocr_engines.py --speed
py -3.13 study_ocr_engines.py --accuracy
```

### Velocidade

Todos os motores sobre a **mesma imagem**, num comando só. Cada motor roda em subprocesso isolado, **sequencialmente, nunca concorrente** — motores CPU-bound competindo pelos mesmos cores distorceriam os números; o isolamento também garante que crash de um motor não derruba os outros, e motor não instalado aparece como `UNAVAILABLE` na tabela em vez de quebrar a rodada. Ver `../specs/f-specs/selecao-motor-ocr.md`.

Duas imagens: **fixture** `captures/20260806-144020_auto.png` (1280x720) e **ao vivo** `captures/20260807-154628_bench_live.png` — frame real da câmera apontada para uma BIOS Positivo, aba Security, 1280x720, nitidez (variância do Laplaciano) 364.

`total` inclui construção do engine; `read` é só a chamada de leitura (custo por frame em uso quente).

### Acurácia

Os 4 motores instalados (`paddleocr`, `rapidocr-openvino`, `rapidocr-onnxruntime`, `winocr`; tesseract segue sem binário) sobre **10 casos com ground truth declarado**, pontuados **através do motor de percepção completo**, não sobre o OCR cru. A escolha é deliberada: quem consome o OCR é o pipeline, e a pergunta que importa não é "quantos caracteres saíram certos" e sim "o motor conclui o estado certo com esse OCR na frente".

Ground truth — todo ele já existente no projeto, nada inventado para o estudo:

| Fonte | Casos | Campo usado |
|---|---|---|
| `TEST_CASES` de `make_test_image.py` | 3 sintéticos, um deles negativo verdadeiro (`test_bios_noselect.png`) | seleção esperada |
| `POSITIVO_CASES` de `test_selection.py` | 5 fotos Positivo | `sidebar` (e `submenu`, ver abaixo) |
| `REAL_CASES` de `test_selection.py` | 2 fotos AMI | seleção esperada |

**Duas métricas, medidas separadamente:** **texto** (o OCR leu a string que o gabarito nomeia — casamento por prefixo em caracteres alfanuméricos) e **seleção** (o motor de percepção concluiu o estado certo). Separá-las é o que permite responder a pergunta em aberto: um motor pode ler o texto perfeitamente e ainda assim o pipeline errar o estado, e vice-versa. Sem essa separação, "acurácia" seria um número único que confundiria falha de OCR com falha de inferência.

**Ressalva metodológica: o primeiro placar estava errado.** A primeira versão da pontuação só olhava o campo `sidebar` do `POSITIVO_CASES` e contava **detecções corretas de submenu como falso positivo** — ou seja, penalizava justamente o motor que acertava mais. `Hardware Monitor`, `Save Changes` e `CPU Overheat Alert Configuration` são submenus corretos declarados no próprio gabarito. O placar abaixo já está corrigido; depois da correção, o único falso positivo genuíno do paddleocr é `Save Options`. Registrado porque o erro é fácil de repetir: o gabarito tem dois níveis (`sidebar` e `submenu`) e pontuar só um deles inverte o ranking.

**Por que o script não reproduz literalmente a tabela de acurácia, e isso é intencional.** A tabela abaixo separa `sidebar` (coluna "Seleção") de `submenu` (coluna própria), porque o gabarito trata submenu como rastreado mas nunca exigido. O script soma os dois num denominador único — 15 alvos em vez de 11 — o que dá, por exemplo, `rapidocr-openvino` em **15/15 de texto e 9/15 de seleção**, contra os `11/11` e `8/11` daqui. São a mesma medição com recortes diferentes, não medições em conflito: o 15/15 confirma que o motor lê *também* todos os rótulos de submenu, reforçando a conclusão 1. O script também **reporta em voz alta** a fixture AMI ausente em vez de pulá-la em silêncio.

### Ressalva de reprodutibilidade (imagens)

Nenhuma das duas imagens da metade de velocidade está no repositório. `git log --all` volta vazio tanto para `captures/20260806-144020_auto.png` quanto para `captures/*_bench_live.png` — o `.gitignore` tem a exceção `!captures/*_bench_live.png` justamente para preservá-las, mas o commit nunca aconteceu e a pasta `captures/` foi esvaziada depois dos testes. **Os números de velocidade não são reproduzíveis a partir de um clone**; uma nova rodada teria que recapturar imagens equivalentes. Ver `../specs/p-specs/fixture-de-teste-nunca-versionada.md`.

## Resultados — velocidade

**Fixture** (`20260806-144020_auto.png`):

| Motor | Total | Read | Linhas |
|---|---|---|---|
| paddleocr | 46.19s | 37.83s | 47 |
| rapidocr-onnxruntime | 7.47s | 4.81s | 45 |
| rapidocr-openvino | 7.11s | 2.77s | 45 |
| winocr | 0.40s | 0.38s | 30 |

**Ao vivo** (`20260807-154628_bench_live.png`):

| Motor | Total | Read | Linhas |
|---|---|---|---|
| paddleocr | 52.60s | **44.09s** | 32 |
| rapidocr-onnxruntime | 12.56s | 7.69s | 31 |
| rapidocr-openvino | 11.88s | **4.53s** | 31 |
| winocr | 0.33s | 0.33s | 20 |

Tesseract: `UNAVAILABLE` nas duas rodadas — binário não instalado (instalação pendente de autorização do usuário).

### Pipeline completo sobre o frame ao vivo

Velocidade só importa se o pipeline continua funcionando. `py -3.13 -m perception.run --summary` sobre o frame ao vivo:

- **`--engine rapidocr-openvino`**: 56 primitivas → 3 regiões → 3 grupos → 5 classes → **1 estado: "Security" selected, conf 0.83**, canais S1_background+S2_chroma, hint nav_menu. "Security" era de fato o item destacado na tela real. Leitura correta, fim a fim, em ~5.5s de OCR quente + <1s das outras 10 etapas.
- **`--engine winocr`**: 45 primitivas, mas **1 grupo, 1 classe, 0 estados** — abstenção `E5.grouping no_regular_arrangement_found`. É ~14x mais rápido que o rapidocr, mas a geometria de linhas dele quebra a detecção de ritmo do E5. Ver `../specs/d-specs/winocr.md`.

## Resultados — acurácia

| Motor | Texto lido | Seleção sidebar | Submenu | Falso positivo real |
|---|---|---|---|---|
| paddleocr | 11/11 | **9/11** | 2/4 | 1 |
| rapidocr-openvino | **11/11** | 8/11 | 1/4 | **0** |
| rapidocr-onnxruntime | **11/11** | 8/11 | 1/4 | **0** |
| winocr | 7/11 | 5/11 | 0/4 | ~9 |

**Leitura da coluna "Submenu".** Os números são baixos para **todos** os motores (2/4 o melhor deles), e isso **não é falha de OCR** — os três motores que leem 11/11 de texto incluem os rótulos de submenu. É a limitação estrutural já documentada em `ESTUDO_SELECAO.md` ("item de submenu com descrição colada embaixo") e em `../specs/p-specs/vazamento-destaque-linha-descricao-adjacente.md`: a barra de destaque vaza cor para a linha de descrição vizinha, que cai na mesma classe de equivalência, e o E7 não consegue separar vencedor de segundo colocado. Trocar de motor de OCR não move esse teto, e a tabela confirma.

Convergência que vale registrar: o motor de percepção mediu 2/4 de "item focado" com o paddleocr em 2026-08-07 (tabela em `../specs/f-specs/motor-percepcao-interface.md`), e esta validação reproduz exatamente 2/4 para o paddleocr — dois caminhos diferentes, três dias de distância, mesmo número.

## Conclusões

1. **Meta <8s atingida** com `rapidocr-openvino`: 4.53s de leitura quente ao vivo, ~5.5s de OCR dentro do pipeline completo, com o resto do pipeline <1s. O paddleocr fica em 37-44s e não entra na disputa desse requisito.
2. **Acurácia de OCR empatada em 11/11** entre paddleocr e rapidocr. A suspeita do modelo `small` lendo pior caiu — ele lê tudo que o paddleocr lê nos 11 alvos do gabarito. A observação informal da metade de velocidade (linhas praticamente iguais: 45 vs 47 na fixture, 31 vs 32 ao vivo) foi confirmada pela medição formal.
3. **Falso positivo: rapidocr é melhor** — 0 contra 1 do paddleocr.
4. **Os dois backends do rapidocr têm acurácia idêntica, linha por linha.** OpenVINO e ONNX Runtime não divergem em nenhum caso. Isso **fecha a escolha de backend**: preferir OpenVINO se justifica só por velocidade (4.53s vs 7.69s), sem nenhum custo de qualidade a ponderar.
5. **O rapidocr-openvino perde em exatamente 1 caso: `test_bios.png`, imagem sintética.** Nas 7 imagens reais empatou ou superou. Causa investigada até o fim, com spec própria: `../specs/p-specs/caixa-de-deteccao-engloba-barra-de-destaque.md`.
6. **winocr está descartado, agora com número.** 7/11 de texto, **0/2 e 0/1 nas duas fotos do AMI** — simplesmente não consegue lê-las —, mais ~9 falsos positivos, incluindo 2 numa imagem que é negativo verdadeiro. Somado à geometria de linhas que quebra o E5, ajustar o E5 não bastaria para destravá-lo. Ver `../specs/d-specs/winocr.md`.

### Veredito honesto

**`rapidocr-openvino` não é "melhor" que o paddleocr em seleção fim a fim** — 8/11 contra 9/11. O que a validação estabelece é mais preciso e mais útil que um vencedor: **empatado** em acurácia de OCR, **equivalente** nas fotos reais (que são a entrada real do projeto), **pior em um caso sintético** por um mecanismo agora conhecido e delimitado, **melhor em falso positivo**, e o **único dentro do requisito de <8s**.

## O default do projeto: a decisão e sua cronologia

A metade de velocidade foi escrita às 15:52 de 2026-08-07 concluindo que o default continuava `paddleocr` e que a troca aguardava validação formal de acurácia. **Quatro minutos depois, `rapidocr-openvino` virou o default** (`ocr.py::DEFAULT_ENGINE`), por decisão explícita do usuário para uso na câmera — e antes daquela validação.

A diferença era de natureza, não de grau: antes, "aguarda validação formal" descrevia um **bloqueio respeitado**; depois, um **risco assumido**. Com a metade de acurácia feita em 2026-08-10, virou **risco medido e delimitado**: o custo está quantificado (1 caso sintético) e a causa desse custo está documentada. A decisão de default não muda; o que mudou é que agora ela se apoia em medição, não em funcionamento observado. O default antigo continua a um flag de distância (`--engine paddleocr`).

## Caminhos descartados (com evidência)

- **Backends acelerados do próprio paddlex (plugin HPI, openvino/onnxruntime)**: não instalam em Windows nativo — falta wheel de `ultra-infer-python`, e a documentação do PaddleX manda usar WSL/Docker. O usuário decidiu explicitamente **não** ir para WSL por ora. Erro literal e detalhes em `../specs/p-specs/paddleocr-cpu-lento-sem-mkldnn.md`.
- **DirectML (`onnxruntime-directml`) na Iris Xe**: **não tentado**, por bugs conhecidos de inferência incorreta nessa iGPU.

## Limitações do gabarito — as duas precisam ficar explícitas

1. **A varredura de ~240 capturas negativas não existe mais.** `test_selection.py` cita esse corpus e o histórico dele (1,4% → 2,0% de falso positivo; também citado em `../architecture/VISUAL_FEATURE_SPEC.md`, `../reference/PROCESSO_OCR.md` e `ESTUDO_SELECAO.md`). Aquelas imagens eram dados de sessão e foram embora. Sobrou **1 negativo verdadeiro** (`test_bios_noselect.png`). Consequência direta: **o número de falso positivo desta validação é muito mais fraco que o histórico e não é comparável com ele** — "0 falsos positivos" aqui significa "nenhum em 1 negativo verdadeiro mais 10 positivos", não "0% em 240 imagens". Ver `../specs/p-specs/fixture-de-teste-nunca-versionada.md`.
2. **Só 2 das 3 fixtures AMI entraram**, porque `captures/20260803-154414` nunca foi commitada (mesma P-spec).

## Pendências

- Tesseract nunca entrou em nenhuma das duas metades — binário não instalado.
- As imagens da metade de velocidade não existem mais (ver a ressalva de reprodutibilidade acima); a metade de acurácia roda sobre fixtures versionadas, exceto a AMI ausente.
