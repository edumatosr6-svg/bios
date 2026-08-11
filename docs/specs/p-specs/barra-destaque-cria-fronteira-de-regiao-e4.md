# A barra de destaque cria a própria fronteira de região que isola o item selecionado

> **Mitigado em 2026-08-07.** Corrigido por um passo de fusão de regiões por continuidade de fundo no E4 — ver "Como foi mitigado" abaixo e `../f-specs/fusao-regioes-continuidade-fronteira.md`. O diagnóstico abaixo fica registrado como está porque é ele que justifica a forma da correção.

## O problema
A barra de destaque da seleção — o retângulo de fundo que marca o item ativo — tem bordas de gradiente fortes o bastante para o E4 lê-las como **fronteira de contexto visual**. O E4 então corta a região exatamente em volta do item destacado, separando-o dos seus pares. Sem pares na mesma região, o E5 não forma grupo com ele, o E6 não o coloca numa classe com os outros itens de menu, e o E7 não tem contra o que comparar — o motor se abstém (`no_channel_singled_out_a_member`).

O efeito é perverso: **quanto melhor a foto, mais provável a falha**. Foto mais nítida → bordas da barra mais definidas → gradiente mais alto no ponto exato onde a barra começa e termina → mais chance de o percentil de borda do E4 (`EDGE_PERCENTILE = 88.0`) promover essas bordas a fronteira. Isso inverte a intuição de operação ("melhorar o enquadramento e o foco melhora o resultado") e é a razão de registrar isso separadamente.

Observado na prática em 2026-08-07, câmera UGREEN ao vivo (`../d-specs/webcam-ugreen-4k.md`) sobre BIOS Positivo real, tela `Setup > Security`, motor de OCR `rapidocr-openvino`.

### Evidência medida: dois frames da mesma tela, mesma sessão, mesmo código

**Ressalva sobre a evidência**: os dois frames citados abaixo **não existem mais** — nunca foram commitados e a pasta `captures/` foi esvaziada depois dos testes. Tudo que resta deles são os números tabelados aqui, que não são reproduzíveis a partir do repositório. Ver `fixture-de-teste-nunca-versionada.md`.

**`captures/20260807-154628_bench_live.png`** — nitidez (Laplaciano) 364, tela **não** preenchendo o frame. Motor **concluiu**: "Security" selected, confiança 0.83, canais `S1_background` + `S2_chroma`.

| | |
|---|---|
| Regiões | Main + Advanced em `r003`; **Security + Boot + Save & Exit + Event Log todos na região-fallback `r001`** (x0 y0 1280x720) |
| Classe do menu | `c005` = `['Security', 'Boot', 'Save & Exit', 'Event Log']` |
| `S1_background` | Security venceu, dev=7.72, ratio=**1.88** (limiar `RUNNER_UP_RATIO = 1.8` — passou raspando) |
| `S2_chroma` | Security venceu, dev=7.12, ratio=5.86 |

**`captures/20260807-161228_bench_live.png`** — nitidez 439, enquadramento melhor, tela preenchendo o frame, título "Setup" agora reconhecido. Motor **absteve**: 0 estados, `E7.state no_channel_singled_out_a_member` 3x.

| | |
|---|---|
| Regiões | `r002` (x36 y0 360x196) levou Main + Advanced; `r004` (x44 y212 360x448) levou Boot + Save & Exit + Event Log |
| Security | caixa y=192..216 (altura 24px), **na costura**: `r002` termina em y=196, `r004` começa em y=212. Só ~4px dos 24 caem dentro de `r004` — abaixo de `MIN_PRIMITIVE_OVERLAP = 0.5`, então Security cai sozinho na região-fallback `r001` |
| Classe do menu | `['Boot', 'Save & Exit', 'Event Log']` — **sem o item destacado** |
| Melhor candidato na classe | `S1_background` winner=`'Boot'`, dev=4.36, ratio=**1.54** (reprovou no ratio) |

A faixa de 16px entre y=196 e y=212, que nenhuma das duas regiões reivindica, é a própria barra de destaque do Security lida como fronteira.

### O que este achado NÃO é
O OCR leu os **seis** itens de menu corretamente nos dois frames (Main, Advanced, Security, Boot, Save & Exit, Event Log), com ritmo vertical regularíssimo: passo ~25px, alinhamento em x dentro de 3px, alturas 22–28px. Geometricamente é um grupo perfeito para o E5. Duas hipóteses foram levantadas e **descartadas por medição** antes de chegar na causa real:

1. **Motor de OCR.** `--engine paddleocr` também dá 0 estados no mesmo frame novo. Não é o motor (ver `../f-specs/selecao-motor-ocr.md`, `../../studies/estudo-motores-ocr.md`).
2. **Tamanho do texto.** A altura mediana do texto caiu de 21.0px para 17.0px num frame intermediário (`captures/20260807-160758_bench_live.png`, também 0 estados, 23 caixas `degenerate_crop` contra 16), o que parecia explicar tudo. Mas no frame final (161228) o texto voltou a ficar maior (só 13 `degenerate_crop`) e **mesmo assim** absteve. Tamanho do texto é fator secundário, não a causa.

Ou seja: não é falha de OCR nem de agrupamento por geometria. **O E5 nunca teve chance** — o E4 já havia separado os itens em regiões diferentes, e o E5 só agrupa dentro de uma região.

## Onde ele mora
- **Causa**: `perception/stages/e4_regionalization.py` — `_segment_contexts` (`EDGE_PERCENTILE = 88.0`, `MIN_REGION_AREA_RATIO = 0.02`) e `_best_region` (`MIN_PRIMITIVE_OVERLAP = 0.5`).
- **Onde aparece**: `perception/stages/e7_state.py` (`MIN_DEVIATION = 3.0`, `RUNNER_UP_RATIO = 1.8`), que é quem emite a abstenção — mas o E7 está agindo corretamente com a informação que recebeu.
- Feature afetada: `../f-specs/motor-percepcao-interface.md`.

## Por que existe
Limitação inerente à abordagem atual do E4, não bug pontual.

`../../architecture/PERCEPTION_PIPELINE_SPEC.md` §E4 e o docstring do módulo definem explicitamente que regiões vêm do **contexto visual da superfície** e não do layout das primitivas ("derivar regiões da distribuição das primitivas cria dependência circular"). A escolha está certa e não deve ser revertida — mas este achado mostra o seu custo:

> Um elemento de **estado** (a barra de seleção, que é conteúdo variável) está sendo lido como se fosse estrutura de **contexto** (fronteira de região).

A barra não delimita dois contextos. Ela marca um item *dentro* de um contexto. O detector de descontinuidade de gradiente não tem como distinguir os dois casos porque olha só para a força da borda, não para a sua extensão nem para o que ela contém. O E4 roda em `WORK_WIDTH = 320` com `SMOOTHING = 9` justamente para que texto e ícones sumam no fundo — uma barra de destaque de largura total sobrevive a esse borramento, texto não.

**Consequência para as métricas já publicadas** (avaliação de antes da correção, mantida por registro): o caso que funcionou (154628) funcionou por **sorte** — o corte do E4 acidentalmente deixou o item destacado na mesma região-fallback que 3 pares. Não havia nada no mecanismo que garantisse isso. Depois da correção esse acerto deixa de depender do acidente; e como o A/B mostrou resultado idêntico nas 9 fixtures versionadas, os números de `../f-specs/motor-percepcao-interface.md` e `../../studies/ESTUDO_SELECAO.md` não mudam — o que muda é que eles deixam de estar apoiados em segmentação acidental nos casos ao vivo.

## Como foi mitigado
**Implementado e validado em 2026-08-07**: passo de **fusão de regiões por continuidade de fronteira** no E4, em `perception/stages/e4_regionalization.py` (`_merge_continuous_contexts`, `_same_background`). O critério é perguntar se o fundo continua do outro lado da fronteira — uma fronteira de contexto de verdade separa dois fundos que diferem exatamente onde se encontram; uma barra desenhada *dentro* de um contexto tem o mesmo fundo dos dois lados dela.

Como funciona, números de discriminação, custo, validação A/B e o limite residual da correção: **`../f-specs/fusao-regioes-continuidade-fronteira.md`**. Em uma linha: os dois frames que abstinham passaram a acertar e as 9 fixtures versionadas deram resultado idêntico com e sem a fusão. Quando a fusão não resolve, o comportamento seguro anterior continua valendo: abstenção em vez de chute, conforme `../../architecture/PERCEPTION_PIPELINE_SPEC.md` §2.

### As outras direções que estavam em aberto, e por que continuam fechadas
A correção age no E4, sobre a fronteira, antes de qualquer coisa depender dela — mas por **continuidade do fundo**, não por extensão/espessura da fronteira, que era a direção óbvia. Foi essa a troca decisiva: extensão exigiria uma noção de "altura de linha", propriedade das primitivas, reencostando na circularidade que o §E4 proíbe.

As outras três continuam **não implementadas e não necessárias** para este caso:
- **Regiões aninhadas/hierárquicas no E4** — segue como questão em aberto de arquitetura (`../../architecture/PERCEPTION_PIPELINE_SPEC.md` §9.2), agora sem este teto como motivação.
- **E5/E6 cruzando fronteira de região** — descartada na prática: mexeria na invariante F2 e exigiria revisão da spec de arquitetura para resolver um problema que se resolveu dentro do E4.
- **Afrouxar `MIN_PRIMITIVE_OVERLAP`** — não foi tocado. Era paliativo e teria mascarado a causa.

## Relação com outros tetos conhecidos — suspeitas a verificar

**Atualização 2026-08-10 — o padrão se confirmou como família.** A generalização que este documento já antecipava em "Por que existe" (a barra de destaque é desenho de superfície e marcador de estado ao mesmo tempo, e o pipeline separa as duas coisas por design, então ela vaza por qualquer canal disponível) se confirmou com casos novos, e ganhou um lado espelhado: quando o traço do marcador não corresponde a nenhum descritor medido, ele **escapa** em vez de contaminar. **Tabela consolidada da família inteira em `caixa-de-deteccao-engloba-barra-de-destaque.md`** — este teto é a entrada "borda → E4" dela.

Nota de escopo (2026-08-10): um A/B novo com e sem a fusão, sobre frames ao vivo da tela de Boot, deu resultado **idêntico** — a fusão não participa daquele episódio (era a suspeita registrada em `../f-specs/fusao-regioes-continuidade-fronteira.md` sobre o `'Standard'`, agora fechada).

As duas suspeitas abaixo continuam não confirmadas; ambas exigem instrumentação antes de virarem afirmação.

- **`vazamento-destaque-linha-descricao-adjacente.md`** — provavelmente **não é a mesma raiz**, mas é a mesma família. Lá o item selecionado *está* na classe com seus pares e o problema é o segundo colocado contaminado pelo vazamento de cor da barra (razão 1.29x); aqui o item nem chega na classe. O que os dois têm em comum é mais profundo que o estágio: **a barra de destaque, que é conteúdo de estado, contamina estágios estruturais anteriores ao E7** — no vazamento pela cor que ela deposita no vizinho, aqui pela borda que ela desenha. Os dois produzem a mesma abstenção `no_channel_singled_out_a_member` por caminhos diferentes, o que torna o motivo da abstenção insuficiente para distinguir os casos no log.
- **`regressao-motor-percepcao-itens-corpo-ami.md`** — suspeita **enfraquecida em 2026-08-07**. A hipótese era que o item de corpo AMI que falha caísse sozinho na região-fallback pelo mesmo corte do E4. O A/B da correção mostrou resultado **idêntico** nas 4 fixtures `captures/20260803-1543*` com e sem a fusão: se o corte do E4 participa daquela regressão, não é do tipo que continuidade de fundo resolve. Não é prova de que o E4 está fora — a fusão só age quando os dois lados têm o mesmo fundo — mas tira a checagem da frente da fila.

## Status
**Mitigado — 2026-08-07.** Diagnosticado (causa isolada no E4) e corrigido no mesmo dia por fusão de regiões por continuidade de fronteira: os dois frames que abstinham passaram a acertar, zero regressão nas 9 fixtures versionadas. Ver `../f-specs/fusao-regioes-continuidade-fronteira.md`.

"Mitigado" e não "fechado" por três motivos: a evidência ao vivo se perdeu do disco (só sobram os números aqui); nenhum teste automatizado exercita a correção; e ela carrega um limite residual próprio — `FRONTIER_REACH` precisa exceder a largura do marcador e falha em silêncio quando não excede, descrito na F-spec da correção.
