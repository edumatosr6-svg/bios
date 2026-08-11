# Fusão de regiões por continuidade de fronteira (E4)

## Objetivo
Passo de fusão dentro do E4 que rejunta o que um **marcador** separou, sem rejuntar o que uma **mudança de contexto** separou. Existe para corrigir o teto registrado em `../p-specs/barra-destaque-cria-fronteira-de-regiao-e4.md`: a barra de destaque da seleção tem bordas fortes o bastante para o detector de descontinuidade de gradiente promovê-la a fronteira de região, o que corta o menu em duas regiões e deixa o item destacado — que fica em cima da costura — sozinho na região-fallback. Sem pares na mesma região, o E5 não forma grupo, o E6 não forma classe e o E7 se abstém. Quanto mais nítida a foto, mais confiável era a falha.

A pergunta que o passo faz é: **o fundo continua do outro lado dessa fronteira?** Uma fronteira de contexto de verdade separa dois fundos que diferem exatamente onde se encontram; uma barra desenhada *dentro* de um contexto tem o mesmo fundo dos dois lados dela.

## Escopo
- **Dentro**: `perception/stages/e4_regionalization.py` — `_merge_continuous_contexts(lab, labels, kept)` (union-find sobre os componentes mantidos) e `_same_background(side_a, side_b)`. Roda depois do `connectedComponentsWithStats` e do filtro de `MIN_REGION_AREA_RATIO`, antes de converter componentes em `Geometry`.
- **Fora**: `EDGE_PERCENTILE` e o detector de bordas não foram tocados — a barra continua sendo detectada como borda, só deixa de virar região separada. A atribuição primitiva→região (`_best_region`, `MIN_PRIMITIVE_OVERLAP = 0.5`) continua igual. Nada mudou em E5/E6/E7. Não implementa regiões aninhadas nem agrupamento cruzando fronteira.

## Comportamento esperado
Entrada: a imagem de trabalho em Lab já suavizada (`WORK_WIDTH = 320`, `SMOOTHING = 9`), o mapa de labels dos componentes conexos e a lista `kept` (componentes que sobreviveram ao filtro de área). Saída: uma lista de **grupos** de labels; cada grupo vira uma única caixa (bbox da união) em vez de uma caixa por componente.

Para cada par (a, b) de componentes mantidos:
1. Amostra a faixa de **a voltada para b** (`masks[a] & dilate(masks[b], FRONTIER_REACH)`) e a faixa de **b voltada para a** (simétrico).
2. Se qualquer lado tiver menos de `MIN_FRONTIER_PIXELS` pixels, pula. Isso também é o teste de adjacência: regiões que não se encaram não contribuem pixel nenhum, por mais parecidas que sejam.
3. Compara as medianas em Lab das duas amostras e funde (union) se a diferença couber em `CONTINUITY_TOLERANCE` vezes a dispersão das próprias amostras, com piso `CONTINUITY_FLOOR`.

Constantes: `FRONTIER_REACH = 8` (px na escala de trabalho), `MIN_FRONTIER_PIXELS = 20`, `CONTINUITY_TOLERANCE = 3.0`, `CONTINUITY_FLOOR = 1.5`.

**Casos de borda**: a fusão é transitiva (union-find), então três fatias de um mesmo fundo viram uma região só. Se *tudo* fundir num único grupo, `_segment_contexts` devolve lista vazia (a guarda `len(boxes) > 1` já existia) e o E4 cai no fallback de região única, registrando a abstenção `no_visual_context_boundary_found` — comportamento preexistente, não alterado aqui.

## Detalhes técnicos

**Por que "o fundo continua?" e não "a fronteira é fina?"** — o teste olha SÓ para a superfície, nunca para as primitivas, respeitando a invariante do §E4 de `../../architecture/PERCEPTION_PIPELINE_SPEC.md` que proíbe derivar regiões do layout do texto. Um critério por extensão/espessura da fronteira (a direção óbvia, registrada no P-spec) precisaria de uma noção de "altura de linha", que é propriedade das primitivas — chega perto da circularidade que a spec proíbe.

**Por que amostrar só perto da fronteira** — é o que mantém compatibilidade com a outra regra do §E4: "um contexto pode variar suavemente e ainda ser um contexto". Um gradiente quase não se move nos poucos pixels comparados, então a sidebar azul-para-branco da Positivo (o caso que motivou segmentação por gradiente em primeiro lugar) continua lendo como um contexto só. Comparar a cor *média* de cada componente inteiro quebraria isso.

**Tolerância em unidades da dispersão da própria amostra**, não em distância de cor fixa: uma foto ruidosa e um screenshot limpo discordam sobre o que é "a mesma cor", e só a amostra pode dizer. Mantém o critério livre de escala e de interface (P1/P6).

**Armadilha que custou uma tentativa errada** — a primeira versão amostrava os pixels colados na fronteira (`dilate(frontier)` interseccionado com cada máscara). Isso caía *dentro* da barra de destaque e media a cor da barra duas vezes, em vez do fundo de cada lado. Sintoma: as tiras saíam com 7 e 9 pixels (abaixo de `MIN_FRONTIER_PIXELS`) e o par nunca chegava a ser testado. A correção foi amostrar a faixa de cada região voltada para a vizinha, com alcance maior que a largura da barra (`FRONTIER_REACH = 8` na escala de trabalho, contra ~4px que a barra ocupa lá).

### Limite residual: o alcance está amarrado à largura do marcador, e a falha é silenciosa

A fusão só funciona enquanto o marcador que criou a falsa fronteira for **mais estreito que `FRONTIER_REACH`** na escala de trabalho. Se for mais largo, as duas faixas amostradas caem *dentro* dele, as duas medianas medem a cor do próprio marcador, e a fusão ou não acontece (poucos pixels amostrados) ou acontece pelo motivo errado. Não é hipótese: é exatamente o que a primeira versão da implementação fez, com as tiras de 7 e 9 pixels acima.

`FRONTIER_REACH` é o **único parâmetro do E4 expresso em pixels absolutos** da escala de trabalho, e o que ele precisa exceder — a largura da barra — é propriedade da interface fotografada, não da superfície medida. Ou seja, é uma constante calibrada indiretamente contra uma família de interfaces, o que atrita com o princípio P1/P6 (nada calibrado a uma interface particular) que o resto do estágio respeita. A folga atual (~4px de barra contra alcance 8) é coincidência entre `WORK_WIDTH = 320` e a proporção da barra nas BIOS testadas, não garantia. Duas mudanças plausíveis disparam a falha: **mexer em `WORK_WIDTH`** (dobrar a resolução de trabalho dobra a largura da barra em pixels sem mexer no alcance, e a folga de 2x vira desvantagem) ou **uma BIOS com barra mais grossa**, ou foto muito mais preenchida pela tela, com o mesmo efeito.

**A falha é silenciosa**: o caminho de erro é um `continue` num laço — não há abstenção nomeada nem nota dizendo "havia um par adjacente que não pôde ser avaliado". Nada implementado contra isso; o que existe é (a) ao mexer em `WORK_WIDTH` ou `FRONTIER_REACH`, reconferir a discriminação contra os números da tabela abaixo — a margem é de mais de uma ordem de grandeza, então uma degradação é fácil de perceber, desde que alguém olhe; (b) correção de verdade seria derivar o alcance da própria superfície (por exemplo, da escala das descontinuidades detectadas), devolvendo o parâmetro à família livre de escala do resto do E4 — não tentado; (c) correção barata de observabilidade seria emitir nota/abstenção quando um par adjacente for descartado por `MIN_FRONTIER_PIXELS`, na linha do princípio de abstenção explícita de `../../architecture/PERCEPTION_PIPELINE_SPEC.md` §2 — não implementada.

**Discriminação medida** (frame ao vivo `20260807-161228`, o mesmo que o P-spec usa como caso de falha):

| Par | Diferença de cor | Limite calculado | Resultado |
|---|---|---|---|
| Menu acima da barra × menu abaixo | **2.26** | 6.81 | fundiu |
| Fronteiras genuínas da mesma tela (10 pares) | **57.50, 63.52, 97.63, 109.93, 113.34, 121.40, 123.25, 135.91, 141.31, 152.61** | — | todas mantidas separadas |

Mais de uma ordem de grandeza separando os dois casos. Não é ajuste fino de limiar — `CONTINUITY_TOLERANCE` poderia mudar bastante sem mudar nenhuma dessas decisões.

**Custo**: 12.9ms médios em 20 execuções para o E4 inteiro (segmentação + fusão), contra ~4.5s do OCR. Irrelevante.

## Critérios de aceite
Validação feita por A/B no mesmo processo, alternando `CONTINUITY_TOLERANCE` entre `-1.0` (fusão desligada) e `3.0` (ligada).

**1. Zero regressão nas 9 fixtures históricas** (5 `positivo_*.jpg`, 4 `20260803-1543*.png`): resultado **idêntico** com e sem a fusão — mesmas contagens de região/grupo/classe, mesmos estados, mesmas confianças.

| Fixture | Estado reportado |
|---|---|
| positivo_advanced_cpu-overheat | 2 estados: 'CPU Overheat Alert C'@0.64 (settings_list) + 'Advanced'@0.73 (nav_menu) |
| positivo_advanced_hardware-monitor | 'Advanced'@0.77 |
| positivo_advanced_mapt | 'Advanced'@0.68 |
| positivo_saveexit_none | 'Save & Exit'@0.79 |
| positivo_saveexit_save-changes | 'Save & Exit'@0.78 |
| 20260803-154317 | nenhum |
| 20260803-154327 | nenhum |
| 20260803-154341 | 'Advanced'@0.83 (tab_bar) |
| 20260803-154356 | 'ACPI'@0.74 (settings_list) |

**2. Os dois frames ao vivo que falhavam passaram a acertar**: `20260807-160758` (nenhum estado → 'Security'@0.80) e `20260807-161228` (nenhum estado → 'Security'@0.78). Captura ao vivo nova, feita depois da correção: 'Security'@0.76.

**3. Rastreamento, não sorte com um item específico**: com a BIOS navegada para outro item (Boot), o motor reportou 'Boot'@0.73 com hint `nav_menu` — acompanha a seleção quando ela se move.

**Não coberto por teste automatizado.** `test_selection.py` importa `from selection import annotate_selection`, ou seja, valida o caminho legado, não o motor de percepção — nenhuma linha dele exercita este passo. Rodado mesmo assim durante a sessão: sintéticos 3/3 OK, AMI reais 2/2 OK, e então `FileNotFoundError` em `captures/20260803-154414_auto.json` (ver `../p-specs/fixture-de-teste-nunca-versionada.md`).

## Status
Concluída — 2026-08-07, revisada em 2026-08-10 (fechamento da pendência do `'Standard'` e absorção aqui do limite residual de `FRONTIER_REACH`, que tinha P-spec separada; nenhuma mudança de código nesta feature). Implementada, medida e validada manualmente (A/B nas 9 fixtures + 3 frames ao vivo + teste de rastreamento). Sem cobertura de teste automatizado.

Um A/B novo em 2026-08-10, sobre frames ao vivo da tela de Boot, deu resultado **idêntico** com e sem a fusão — reforça que os desfechos daqueles frames não dependem deste passo.

## Questões em aberto
- ~~**Pendência não checada**: no frame do "Boot", além do acerto em 'Boot'@0.73, o motor reportou também `selected: 'Standard'@0.82` num `settings_list`.~~ — **Fechada em 2026-08-10**, e nenhuma das duas partes do desfecho é a que se supunha: (1) **sem relação com esta fusão** — A/B com e sem ela deu resultado idêntico nos frames ao vivo novos; (2) **não era falso positivo** — o `Standard` tinha mesmo o anel de foco. O que a verificação achou no lugar são dois tetos próprios: `../p-specs/campo-focado-por-borda-sem-canal-no-e7.md` (aberto) e `../p-specs/classe-fina-canal-unico-eleito-por-ruido.md` (mitigado).
- **A evidência ao vivo não existe mais em arquivo.** Os frames `captures/*_bench_live.png` usados na validação nunca foram commitados e a pasta `captures/` foi esvaziada depois dos testes; os números acima são a única evidência sobrevivente dos casos ao vivo, e não são reproduzíveis a partir do repositório. Padrão e consequências em `../p-specs/fixture-de-teste-nunca-versionada.md`.
- O parâmetro `FRONTIER_REACH` tem que ser maior que a largura do marcador na escala de trabalho, e a falha quando não é é silenciosa — limite residual descrito acima em "Detalhes técnicos"; aberto, sem correção nem observabilidade.
- Não existe `test_perception.py`; enquanto não existir, esta feature só é verificável por medição manual.
