# VISUAL_FEATURE_SPEC — Gramática Visual do Motor de Percepção de Interface

**Status:** rascunho para discussão (v0.2) · **Data:** 2026-08-05
**Escopo:** *quais propriedades visuais o motor deve medir.* Não define arquitetura (ver `PERCEPTION_PIPELINE_SPEC.md`) e não define técnica.

## Convenção de leitura — normativo vs. informativo

Esta especificação distingue dois níveis, e a distinção é vinculante:

| Nível | Significado | Exemplo |
|---|---|---|
| **Normativo** | O que **deve** ser verdade. Mudar exige revisar esta spec | "a comparação de cor deve usar uma métrica perceptualmente uniforme" |
| *Informativo* | Como isso **poderia** ser obtido hoje. Substituível sem revisar nada | *"por exemplo, ΔE em espaço perceptual"* |

Toda técnica nomeada neste documento — espaço de cor, estatística, transformada, biblioteca — é **informativa**. Aparece porque nomear um caminho conhecido acelera a implementação e ancora a discussão, nunca porque a especificação a exige. Se uma técnica melhor aparecer, troque-a: a especificação continua válida.

**Hierarquia de documentos:**

| Documento | Autoridade | Não decide |
|---|---|---|
| `PERCEPTION_PIPELINE_SPEC.md` | Objetos, estágios, fluxo | O que medir; como medir |
| `VISUAL_FEATURE_SPEC.md` (este) | Quais propriedades medir | Como medir; arquitetura |
| Decisões de implementação | Como medir | Nada acima |

Este documento nunca pode contradizer o de cima.

---

## 1. Propósito e fronteira

O Motor de Percepção de Interface (daqui em diante **IPE**) converte imagens de uma tela de firmware em uma **descrição estrutural falsificável** da interface.

O IPE responde, e apenas:

| Pergunta | Resposta do IPE |
|---|---|
| O que existe na tela? | Inventário de primitivas (texto e não-texto) |
| Como a tela está organizada? | Árvore de regiões, grupos e elementos |
| Que elementos formam um conjunto? | Classes de equivalência visual |
| Qual elemento difere dos seus pares, e em que canal? | Estados, com evidência e confiança |
| Estamos na mesma tela de antes? | Impressão digital estável de tela (`screen_id`) |

O IPE **não** responde: o que a tela significa, se uma configuração está correta, qual tecla apertar, para onde navegar. Isso é cognição, e pertence à etapa seguinte.

**Consequência de projeto frequentemente ignorada:** como não existe LLM revisando a percepção, um erro confiante do IPE é irrecuperável a jusante. Portanto a especificação trata *abstenção* e *incerteza* como saídas de primeira classe, não como casos de borda.

---

## 2. Crítica da arquitetura proposta

Esta seção existe porque a especificação foi pedida com análise crítica. Cada ponto abaixo mudou o desenho apresentado nas seções 3–12.

### C1 — "Sem heurísticas por fabricante" é uma meta de código, não uma meta verificável

Escrever zero `if vendor == "positivo"` é fácil. Provar independência de fabricante é outra coisa: se os limiares forem calibrados olhando os três modelos-alvo, não existe evidência de que o motor generalize — só de que ele memorizou três casos.

**Correções adotadas:** (a) distinção formal entre *mecanismo* (invariante, versionado) e *parâmetro* (derivado da própria tela em tempo de execução); (b) protocolo obrigatório de **validação com fabricante retido** (§11.3): calibrar em N−1 fabricantes, medir no N-ésimo nunca visto.

### C2 — O motor está desenhado a jusante do OCR, e isso o cega

No pipeline atual (`Captura → Estável → OCR → Motor`), a única fonte de primitivas é o OCR. Mas metade da estrutura de uma interface **não tem texto**: barras de seleção, separadores, molduras de campo, sombras de modal, scrollbars, ícones, o cursor de edição. Um motor que só enxerga caixas de texto nunca vai perceber que existe um painel, uma janela sobreposta, ou que há mais itens fora da tela.

Além disso, a segmentação do OCR **não é a segmentação da interface**. `ocr.py` agrupa em `blocks`/`lines` por critérios do motor de OCR — no caso do PaddleOCR, tudo vira `block_num: 0` (veja [ocr.py:177](ocr.py:177)). Tratar "linha do OCR" como "elemento de UI" é herdar um artefato de OCR como se fosse fato de interface.

**Correção adotada:** o OCR passa a ser *uma* fonte de primitivas entre duas. O pipeline é reescrito como fusão (§4), não como cadeia.

### C3 — Falta a camada de normalização, e sem ela metade das features propostas é ruído

A lista de features propostas contém `background_color`, `brightness`, `saturation`, `hue`, `distância`, `alinhamento`, `largura`, `altura`. Todas essas grandezas são medidas **em pixels de uma foto de uma tela**, e portanto contaminadas por: perspectiva, distorção de lente, iluminação não uniforme, reflexo, moiré, temperatura de cor da câmera, ganho automático, vinheta, desfoco nas bordas.

A imagem `Circulado_novo.jpeg` demonstra os três piores casos ao mesmo tempo:
- a coluna esquerda **não tem cor de fundo constante** — é um gradiente vertical de azul para quase branco;
- a tela está fotografada em ângulo, então "alinhamento vertical" e "mesma largura" não são medíveis diretamente;
- há região com brilho estourado (canto inferior esquerdo), onde toda medida de cor é inválida.

**Correção adotada:** camada **L0 de normalização** (retificação geométrica + normalização fotométrica + máscara de validade) torna-se obrigatória, e toda feature carrega um flag de validade de medição.

### C4 — Cor absoluta é a feature mais frágil da lista; relação de cor é a mais forte

`background_color: #1A3A6B` não significa nada entre fabricantes, nem entre duas fotos da mesma máquina. O que carrega sinal é sempre uma **relação**: este elemento contra seus pares, esta tinta contra este fundo local.

Dois refinamentos técnicos: medir em espaço perceptual (**CIELAB**, distância **ΔE**) em vez de distância euclidiana em BGR — o código atual usa L2 em BGR ([selection.py:96](selection.py:96)), que não é perceptualmente uniforme; e **separar luminância (L\*) de cromaticidade (a\*b\*)**, porque são canais de sinal diferentes: "item desabilitado" é tipicamente uma queda de contraste em L\*, "item selecionado por cor de texto" é tipicamente um desvio em a\*b\*. Colapsar os dois em uma distância única destrói essa distinção.

### C5 — A taxonomia de componentes mistura o que é decidível por pixels com o que é semântica

Na lista proposta, "Menu Vertical", "Lista" e "Tabs" são **visualmente indistinguíveis**: os três são N elementos semelhantes, alinhados, com passo regular, um deles em estado diferente. A diferença entre eles é *comportamental*, não visual — só se sabe que é um "Tab" depois de apertar e ver o painel trocar.

Afirmar "isto é um TabBar" na camada de percepção é exatamente cognição infiltrada na percepção — viola o princípio central do projeto.

**Correção adotada:** o IPE emite **tipos estruturais falsificáveis** (`Repeater(axis)`, `KeyValueTable`, `Region`, `Overlay`…) como fato, e **papel semântico** (`tab_bar`, `nav_menu`) apenas como `semantic_hint` com confiança, em campo separado, que a camada de cognição pode ignorar ou sobrescrever.

### C6 — "Estado" foi modelado como propriedade do elemento; é propriedade do elemento *dentro de uma classe*

Esta é a observação mais consequente, e o projeto já chegou nela sozinho ("o motor não procura o item selecionado; procura se existe algum elemento visualmente diferente dos outros"). Vale levar até o fim:

> Um estado não é uma medida. É uma **anomalia de uma medida em relação a uma população de referência**. Sem população, não existe estado.

Disso decorre a inversão de prioridade mais importante desta especificação:

> **O problema difícil não é detectar estado. É construir a classe de equivalência correta.** A qualidade da detecção de estado é limitada superiormente pela qualidade do agrupamento.

O caso da Positivo confirma: o motor atual não erra o cálculo de cor — ele agrupa errado. `_cluster_rows` ([selection.py:154](selection.py:154)) só reconhece região como *fileira horizontal*, então cada item do menu vertical vira uma fileira de um elemento, não atinge `MIN_STRIP_SIZE`, cai no balde `body`, e acaba comparado contra a mediana da **tela inteira** — que mistura a coluna azul clara com o painel escuro. Não há limiar que conserte isso; a população de referência está errada.

### C7 — A dimensão temporal está ausente da especificação, e é o sinal mais invariante disponível

O estudo já mediu (`../studies/ESTUDO_SELECAO.md`, método 5): diferença temporal acerta 5/5 em condição ideal e é o único sinal que **não depende de paleta, polaridade, layout ou fabricante**. Com câmera fixa em fixture industrial, é o candidato mais robusto que existe — e o pipeline atual descarta essa informação ao tratar cada captura como imagem única.

Há ainda sinais temporais que nenhum método de quadro único alcança: **o caret piscando** (prova determinística de campo em edição) e **o painel de ajuda que muda junto com o foco** (corrobora qual item está focado, por conteúdo em vez de por cor).

**Correção adotada:** o IPE é especificado sobre um **feixe de quadros** (`FrameBundle`), não sobre um quadro. Ver §9 e o trade-off de estado em §12.

### C8 — Falta incerteza de primeira classe

`selected: true` sem confiança e sem evidência obriga a camada de cognição a confiar cegamente ou desconfiar de tudo. O motor atual já pratica abstenção implícita (`MAX_TEXT_COLOR_OUTLIERS = 1`: várias linhas estranhas ⇒ nenhuma seleção), mas isso não aparece na saída — some silenciosamente.

**Correção adotada:** todo fato derivado carrega `confidence`, `evidence[]` e `method`; e `UNKNOWN`/`ABSTAINED` são valores legítimos de estado, distintos de "ausente".

### C9 — Uma especificação sem protocolo de avaliação por camada não é falsificável

Métrica só de ponta a ponta esconde onde o erro nasce. Se a taxa de acerto cai, é primitiva perdida, agrupamento errado ou canal de estado mal calibrado? Sem métrica por camada, a resposta vira opinião. §11 define métricas separadas por camada.

### C10 — Antes de investir em visão computacional, vale questionar a captura

Como arquiteto seria negligência não colocar isto na mesa: **boa parte de L0 existe para desfazer um problema que a escolha de captura criou.**

| Canal alternativo | O que elimina | Custo/risco |
|---|---|---|
| **Captura HDMI/DP** (dongle de captura no lugar da câmera) | Perspectiva, moiré, reflexo, vinheta, desfoco, temperatura de cor. Cor vira exata; features geométricas viram exatas. | Requer saída de vídeo acessível na máquina alvo; não serve se o alvo for notebook sem saída ativa na POST. |
| **Serial console redirection** (comum em firmware corporativo) | Praticamente todo o problema visual: entrega texto e posição de cursor literalmente. | Nem todo modelo habilita; pode não refletir a UI gráfica; exige acesso à porta. |
| **Câmera** (atual) | — | Máxima generalidade: funciona em qualquer máquina, sem depender de recurso do firmware. |

Não é recomendação de trocar a câmera — a generalidade dela é um ativo real, e a fábrica pode ter máquinas sem alternativa. Mas se **algum** dos três modelos-alvo suportar HDMI ou serial, esse canal deveria ser usado ao menos como **fonte de verdade para calibrar e validar o motor visual** (§11.1), o que é muito mais barato que anotar tudo à mão.

> **Alerta medido (2026-08-10), a ler antes de adotar captura HDMI/DP.** A tabela acima lista só o que a captura limpa *elimina*. Ela também **introduz** um problema: com bordas duras (imagem gerada por software, sem ruído de câmera), o detector de texto do OCR passa a englobar a barra de destaque dentro da caixa do item selecionado, contaminando os descritores do E3 e o agrupamento do E6, e o motor se abstém. Medido em imagem sintética — que é o análogo mais próximo de captura HDMI que o projeto tem hoje: razão de altura de caixa 1.64 contra 1.03-1.10 em foto real. Ver `../specs/p-specs/caixa-de-deteccao-engloba-barra-de-destaque.md`. Não invalida a recomendação; significa que trocar o canal de captura exige revalidar o motor contra o gabarito, não só assumir que entrada melhor dá resultado melhor.

---

## 3. Princípios invioláveis

Regras que qualquer decisão futura do motor deve respeitar. Violação exige revisão desta especificação, não exceção pontual.

**P1 — Relatividade.** Nenhuma decisão sobre estado depende de constante absoluta de cor, tamanho ou posição. Toda medida é comparada contra uma população derivada da própria tela.

**P2 — Falsificabilidade.** A camada de percepção só afirma como fato aquilo que é decidível a partir dos pixels. O que exige conhecimento de comportamento ou de domínio é `hint` com confiança, nunca fato.

**P3 — Abstenção preferível a chute.** "Não há seleção detectável neste grupo" é uma saída correta e desejável. Precisão alta com cobertura declarada vale mais que cobertura total com erro silencioso.

**P4 — Evidência rastreável.** Todo fato derivado carrega as medições que o produziram e o método que o decidiu. Nenhuma afirmação aparece no JSON sem proveniência.

**P5 — O bruto sempre acompanha o interpretado.** A saída carrega as camadas inferiores junto com as superiores. Se a interpretação estiver errada, a cognição ainda tem material para se recuperar. (Generaliza o que `raw_ocr` já faz hoje.)

**P6 — Mecanismo invariante, parâmetro auto-calibrado.** Independência de fabricante significa: nenhum caminho de código por fabricante. Calibração automática *por tela* não só é permitida como obrigatória.

**P7 — Determinismo e reprodutibilidade.** Mesma entrada ⇒ mesma saída, bit a bit. Sem amostragem aleatória não semeada. Schema e conjunto de parâmetros são versionados e aparecem na saída.

**P8 — Separação percepção/cognição.** Sem exceções, sem "só esse caso".

---

## 4. Modelo em camadas

> **Autoridade:** a arquitetura é definida por `PERCEPTION_PIPELINE_SPEC.md`, que estabelece a cadeia de objetos — **Primitiva → Região → Grupo → Classe de Equivalência → Estado → Contrato** — e os estágios que a produzem. Esta seção é a visão da mesma arquitetura sob a ótica das *features*: onde cada família de medida entra. Em caso de divergência, o documento de arquitetura prevalece.

Cada camada consome **apenas** a camada imediatamente inferior. Essa restrição é o que permite testar, medir e substituir camadas isoladamente (§11.2).

```
        FrameBundle (N quadros estáveis + metadados de captura)
                              │
   L0  NORMALIZAÇÃO ─────────►  quadro canônico + máscara de validade + laudo de qualidade
                              │
   L1  PRIMITIVAS ───────────►  união de duas fontes independentes:
        ├── textuais (OCR)         glifos/palavras/linhas + quad + confiança
        └── estruturais (CV)       regiões, réguas, retângulos, bordas,
                                   blobs de ícone, scrollbar, caret
                              │
   L2  APARÊNCIA ────────────►  vetor de estilo por primitiva (relativo e local)
                              │
   L3  AGRUPAMENTO ──────────►  árvore: Região ▸ Grupo ▸ Elemento
        (Gestalt)                 + classes de equivalência  ◄── camada crítica
                              │
   L4  ESTADO ───────────────►  anomalia relativa por canal, com evidência,
        (anomalia relativa)       confiança e abstenção
                              │
   L5  TIPAGEM ──────────────►  tipos estruturais falsificáveis + semantic_hints
                              │
   L6  IDENTIDADE/TEMPO ─────►  screen_id estável, deltas, piscadas, transições
                              │
   L7  CONTRATO ─────────────►  JSON versionado (visão full + visão digest)
```

Observe onde o motor atual vive: `selection.py` faz, misturados numa passada só, pedaços de L2, L3 e L4, sem L0, sem L1 estrutural e sem L6. A separação acima é a mudança arquitetural principal desta especificação.

### L0 — Normalização (obrigatória)

| Etapa | Objetivo | Nota |
|---|---|---|
| Detecção do quadrilátero da tela | Achar a área útil do painel | Bordas fortes + maior quadrilátero convexo plausível |
| Retificação por homografia | Remover perspectiva; coordenadas viram canônicas | Torna alinhamento/passo/tamanho comparáveis |
| Achatamento de iluminação | Remover gradiente de iluminação **da cena** | **Cuidado:** não pode apagar gradiente que é *design da UI* (a coluna da Positivo). Estimar iluminação em escala espacial grossa e só corrigir o que for mais suave que a estrutura da UI |
| Normalização fotométrica | Estabilizar branco/ganho entre capturas | Referência preferencial: regiões acromáticas da própria tela |
| Máscara de validade | Marcar pixels inválidos | Estouro/clipping, reflexo especular, borrão, moiré |
| Laudo de qualidade | Foco (variância do Laplaciano), % de área inválida, contraste global | Gate: abaixo do mínimo, o feixe é rejeitado antes de gastar OCR |

**Saída:** quadro canônico + máscara + laudo. Nada semântico.

> **Escalonamento (importante).** A tabela acima é o L0 **maduro**, não o L0 da v1. Construí-lo inteiro antes de validar o conceito é custo sem retorno demonstrado. A v1 mínima é **apenas a retificação geométrica** — suficiente para tornar posição, tamanho, passo e alinhamento comparáveis, que é do que o agrupamento precisa. Normalização fotométrica e máscara de validade entram na v2, e só se a variação de observação se mostrar **medidamente** a fonte dominante de erro. Ver a tabela de maturidade em `PERCEPTION_PIPELINE_SPEC.md` §6.

### L1 — Primitivas

Duas fontes **independentes**, fundidas por geometria. Independência é o ponto: falha de uma não cega a outra.

**Textuais (OCR).** Glifos/palavras/linhas com quadrilátero, confiança, e a *polilinha* original quando o motor fornecer. Nota: `_box_to_bbox` ([ocr.py:187](ocr.py:187)) hoje reduz a saída do PaddleOCR a um retângulo alinhado aos eixos, descartando a inclinação — informação útil para estimar rotação residual e para recortes mais justos.

**Estruturais (CV clássica, sem texto).** Regiões de fundo (incluindo regiões com **gradiente suave**, não só uniformes), réguas/separadores, retângulos preenchidos e vazados, bordas e raio de canto, sombras, blobs não-textuais (ícones), scrollbar, caret.

**Regra:** L1 não agrupa e não interpreta. `blocks`/`lines` do OCR são preservados como metadados de proveniência, **não** como estrutura de interface (C2).

### L2 — Aparência

Vetor de estilo por primitiva, medido localmente. Catálogo completo em §5. Duas decisões de medição herdadas do motor atual e mantidas por serem corretas:

- **fundo amostrado no anel de perímetro do bbox**, não no recorte inteiro — a tinta se concentra no miolo, e "cor mais comum do recorte" costuma ser a cor da letra (cobertura de tinta medida em 51–73%);
- **tinta estimada pelo percentil de maior distância ao fundo**, não pela média do recorte.

### L3 — Agrupamento perceptual — §6

### L4 — Estado por anomalia relativa — §7

### L5 — Tipagem falsificável — §8

### L6 — Identidade de tela e tempo — §9

### L7 — Contrato de saída — §10

---

## 5. Catálogo de Visual Features

**Como ler as tabelas.** A coluna *O que mede* é **normativa**: define a propriedade que precisa existir. A coluna *Observação* é **informativa**: contém técnicas conhecidas, nomeadas como ponto de partida, nunca como exigência. Nenhuma técnica citada aqui é vinculante.

**Robustez** é estimada sob captura por câmera: A = confiável · B = usável após condicionamento · C = frágil, só como evidência corroborante.

### 5.1 Fotometria (sempre relativa)

**Requisito normativo desta família:** toda comparação de cor deve usar uma métrica **perceptualmente uniforme**, e deve manter **luminância e cromaticidade como canais separados** — são canais de sinal distintos (atenuação vs. troca de cor de texto) e colapsá-los numa distância única destrói a distinção (C4).

| Feature | O que mede *(normativo)* | Robustez | Observação *(informativa)* |
|---|---|---|---|
| `bg_local` | Cor do fundo no entorno imediato do elemento | A | Amostrar pelo perímetro do bbox, com estatística robusta — a tinta se concentra no miolo. Medida local, nunca global |
| `ink_color` | Cor da tinta do elemento | A | Ex.: pixels de maior distância ao fundo local |
| `contrast_polarity` | Se a tinta é mais clara ou mais escura que seu fundo local | **A+** | Invariante a paleta. Separação medida de −191 vs +240 (sintéticos) e +45 vs −118 (fotos reais). O sinal mais forte da família |
| `contrast_magnitude` | Intensidade do contraste tinta/fundo local | A | Ex.: contraste de Weber ou Michelson. Base para detectar `disabled` |
| `delta_luminance_vs_peers` | Desvio de **luminância** contra os pares da classe | A | Canal de atenuação (*dimming*) |
| `delta_chroma_vs_peers` | Desvio de **cromaticidade** contra os pares da classe | A | Canal de cor de texto. Mantido separado da luminância por decisão (C4) |
| `bg_uniformity` | Quão homogêneo é o fundo do elemento | A | Barra de seleção é preenchimento chapado; distingue barra real de ruído |
| `saturation_rel` | Saturação relativa aos pares | B | `disabled` costuma dessaturar |
| `hue_abs` | Matiz **absoluto** | **C** | Instável sob balanço de branco automático. Nunca decisivo sozinho |
| `photometric_validity` | Fração de área mensurável do elemento | A | Vem do mapa de validade do condicionamento. Invalida as demais features quando baixa |

### 5.2 Tinta e tipografia (sem fonte de referência)

O motor atual descarta detecção de peso por falta de baseline absoluto ([selection.py:71](selection.py:71)). **Essa recusa merece revisão:** como todo estado é relativo (P1), não é preciso baseline absoluto — basta comparar com os irmãos do mesmo grupo, que compartilham fonte e corpo por construção.

| Feature | O que mede *(normativo)* | Robustez | Observação *(informativa)* |
|---|---|---|---|
| `visual_weight` | **Peso visual do traço**, comparável entre membros da mesma classe | B | Requisito é o peso, não a técnica. Ex.: espessura média do traço, densidade de tinta, ou resistência a erosão morfológica — a escolha é livre e substituível |
| `body_metrics` | Proporções do corpo do texto (altura de caixa alta/baixa) | B | Distingue título de corpo |
| `case_ratio` | Proporção de glifos em caixa alta | A | Derivável do conteúdo legível; robusto |
| `tracking` | Espaçamento médio entre glifos | C | Útil só para detectar troca de fonte |

**Fora de escopo:** identificar família tipográfica. Não é decidível de forma confiável nesta resolução, e nada no domínio depende disso.

### 5.3 Geometria e ritmo (insumo do agrupamento)

| Feature | O que mede | Robustez | Observação |
|---|---|---|---|
| `bbox_canonical` | Caixa em coordenadas retificadas normalizadas | A | Só significativo após L0 |
| `alignment_edge` | Aresta de alinhamento dominante (esq./dir./centro) e sua força | A | Gestalt: continuidade |
| `pitch`, `pitch_regularity` | Passo entre elementos e desvio do passo | **A+** | Assinatura de *repetidor*, independente de eixo |
| `axis` | Eixo dominante do arranjo | A | **Inferido, jamais assumido** — origem do bug da Positivo |
| `indent_level` | Indentação relativa dentro do grupo | A | Revela hierarquia de submenu |
| `column_band` | Faixa vertical de tabulação | A | Base do pareamento rótulo↔valor |
| `local_density` | Densidade de primitivas na vizinhança | B | Separa painel denso de área vazia |
| `aspect_ratio`, `area_rel` | Forma e tamanho relativos | A | |

### 5.4 Primitivas estruturais não-textuais (a lacuna do desenho atual)

| Feature | O que mede | Robustez | Por que importa |
|---|---|---|---|
| `separator_rule` | Linha fina longa | A | Delimita região sem depender de cor de fundo |
| `filled_rect` | Retângulo preenchido | A | A barra de seleção **como forma**, não como cor |
| `border_box` / `corner_radius` | Moldura e arredondamento | B | Campo de valor, botão, caixa de foco |
| `drop_shadow` | Sombra projetada | B | Evidência forte de **overlay/modal** |
| `icon_blob` | Blob não-textual alinhado ao texto | B | Assinatura de forma; **não** classificar o ícone |
| `scrollbar` + `thumb_ratio`/`thumb_pos` | Barra de rolagem e proporção do polegar | A | **Informa quantos itens existem fora da tela** — crítico para um agente que precisa navegar |
| `caret` | Cursor de texto (via piscada, §9) | A | Prova determinística de modo de edição |
| `chevron` / `submenu_arrow` | Seta ao fim da linha | B | Indica item navegável vs terminal |
| `embedded_state_glyph` | `[X]`, `[ ]`, `<>`, `►`, `▲▼`, `*` | **A** | Em firmware, muito estado é **textual**. Deve virar estado, não sobrar como texto solto |
| `key_legend_band` | Faixa com padrão `tecla: ação` | A | Entrega o **vocabulário de ações da tela** — insumo de altíssimo valor para a cognição |

### 5.5 Relações

| Feature | O que mede | Robustez |
|---|---|---|
| `parent_region`, `group_id`, `index_in_group` | Contenção e pertencimento | A |
| `neighbors_by_axis` | Vizinhos imediatos no eixo do grupo | A |
| `label_value_pair` | Pareamento rótulo↔valor por faixa de coluna | A |
| `help_panel_link` | Correlação entre item focado e painel de ajuda | B (temporal) |
| `equivalence_class_id` | Classe de referência usada para julgar estado | **A — obrigatória em toda decisão de estado** |

### 5.6 Temporais (§9)

| Feature | O que mede | Robustez |
|---|---|---|
| `change_mask` | O que mudou entre quadros estáveis | A (câmera fixa) |
| `highlight_transition` | Par (origem, destino) do salto do destaque | **A+** quando há navegação |
| `blink_period` | Periodicidade de piscada | A |
| `primitive_persistence` | Presença ao longo de N quadros | A |
| `region_stability` | Ruído por região | A |

### 5.7 Qualidade e incerteza

`focus_measure`, `clipping_ratio`, `moire_energy`, `glare_mask`, `ocr_confidence`, `measurement_valid` — todas por primitiva **e** por região. Nenhuma feature entra em decisão de estado com `measurement_valid = false`.

---

## 6. Agrupamento perceptual (L3) — a camada crítica

Por C6, esta é a camada que determina o teto de qualidade do motor.

### 6.1 Princípio

Agrupar por **princípios de Gestalt**, todos independentes de fabricante e de eixo:

| Princípio | Uso no IPE |
|---|---|
| Região comum | Elementos sobre o mesmo fundo pertencem à mesma região |
| Similaridade | Elementos com vetor de estilo próximo formam classe de equivalência |
| Proximidade | Distância pequena relativa à distribuição da própria tela |
| Continuidade | Alinhamento em aresta comum |
| Repetição / ritmo | Passo regular ao longo de um eixo inferido |

### 6.2 Estrutura em três passos

**Passo 1 — Regiões (região comum).** Segmentar o quadro canônico em regiões de fundo **antes** de olhar as primitivas. Isso resolve o bug da Positivo na raiz: a coluna esquerda e o painel direito viram regiões distintas por terem fundos distintos, independentemente de os itens estarem em coluna ou em fileira.

> **Requisito não negociável:** o segmentador precisa aceitar região com **gradiente suave** como uma única região. Um detector de "cor uniforme" quebra na coluna da Positivo, que vai de azul a quase branco. Recomenda-se segmentação guiada por *borda* e por *continuidade de gradiente*, não por constância de cor.

**Passo 2 — Grupos (similaridade + proximidade + ritmo).** Dentro de cada região, construir um grafo sobre as primitivas com peso combinando similaridade de estilo, proximidade e alinhamento; extrair componentes; testar cada candidato quanto a **ritmo repetido** ao longo do eixo inferido. Aceitar como `Repeater` quando a regularidade do passo for alta e a cardinalidade ≥ 3.

Nada nesse passo assume horizontal ou vertical: o eixo é uma **saída**, não uma premissa.

**Passo 3 — Classes de equivalência.** Dentro de um grupo, membros que compartilham papel estrutural (mesma faixa de coluna, mesmo nível de indentação, mesmo corpo) formam a classe de referência contra a qual o estado será julgado em L4. Um grupo pode conter mais de uma classe — rótulos e valores de uma tabela são classes distintas e não devem ser comparados entre si.

### 6.3 Alternativa considerada, e por que fica em segundo plano

*Comparar cada elemento apenas com seus k vizinhos imediatos*, dispensando a construção de regiões. É mais simples e evita errar a classificação de região por construção. Contra: perde a noção de cardinalidade do grupo (não sabe dizer "há exatamente uma seleção neste menu de 6 itens"), degrada em fronteira entre regiões e não produz a árvore que o contrato de saída exige. **Recomendação:** manter como *fallback* quando o Passo 1 não atingir confiança mínima — degradação graciosa, não substituto.

---

## 7. Inferência de estado (L4)

### 7.1 Definição

Para um elemento `e` de classe de equivalência `C` e uma feature `f`, o **desvio** de `e` é o quanto `f(e)` se afasta da população de referência, medido **em unidades da dispersão dessa própria população**.

Três requisitos **normativos**, e nada além deles:

1. **Referência robusta.** Tendência central e dispersão devem resistir a valores extremos — um único membro atípico não pode arrastar a referência.
2. **Referência escalada pela própria dispersão.** O desvio é expresso em relação a quanto a população naturalmente varia, não em unidades absolutas. É isso que dispensa recalibração por interface (P1/P6).
3. **Auto-exclusão.** O elemento sob teste **não** participa da própria referência. Sem isso, um destaque forte contamina a referência e se esconde — efeito severo em classes pequenas, que são a regra em menus.

*Informativo: mediana como tendência central e desvio absoluto mediano como dispersão satisfazem os três requisitos e são o ponto de partida sugerido. Qualquer estimador robusto equivalente serve.*

### 7.2 Canais de sinal

Estado nunca é decidido por uma distância única, e sim por **qual canal disparou**. É o que permite distinguir estados diferentes e é a base da independência de fabricante: cada fabricante marca por um canal diferente, e o motor cobre todos.

| # | Canal | Anomalia | Estado tipicamente indicado |
|---|---|---|---|
| S1 | Fundo invertido | `bg_local` distante do fundo da região + `bg_flatness` alta | `selected` (barra) |
| S2 | Cromaticidade da tinta | `delta_ab_vs_peers` alto, `L*` estável | `selected` (cor de texto) |
| S3 | Polaridade / luminância | `contrast_polarity` invertida vs pares | `selected`, `highlighted` |
| S4 | Peso do traço | `stroke_width` / `erosion_survival` acima dos pares | `focused`, `active` |
| S5 | Atenuação | `contrast_magnitude` e `saturation_rel` **abaixo** dos pares | `disabled` |
| S6 | Moldura | `border_box` presente só neste elemento | `focused` |
| S7 | Temporal | elemento é destino de `highlight_transition` | `selected` (corroboração forte) |
| S8 | Glifo embutido | `[X]`, `►`, `*` | `checked`, `expanded`, `modified` |
| S9 | Piscada | `blink_period` compatível com caret | `in_edit_mode` |

### 7.3 Regra de decisão (escala-livre)

O teste do "vice-campeão" já usado para a barra de menu ([selection.py:214](selection.py:214)) é a ideia certa e deve ser **promovida de caso especial a regra geral**, porque não exige calibração de distância absoluta — logo, não exige recalibração por fabricante (P6):

1. **Piso:** o candidato precisa superar um piso mínimo de desvio (evita ruído puro).
2. **Margem sobre o vice:** o primeiro colocado precisa superar o segundo colocado por uma razão. Este é o teste escala-livre; é ele que carrega a independência de fabricante.
3. **Cardinalidade:** respeitar o prior do grupo (menu ⇒ no máximo um `selected`; lista de checkbox ⇒ qualquer número de `checked`).
4. **Acúmulo entre canais:** canais concordantes elevam a confiança; canais em conflito a reduzem.
5. **Abstenção:** empate dentro da margem, conflito entre canais, ou classe pequena demais para estatística ⇒ `UNKNOWN` com motivo explícito. Nunca chutar.

### 7.4 Vocabulário de estados

Além dos propostos, estes são **críticos para um agente de automação** e faltavam:

`selected` · `focused` · `highlighted` · `active` · `disabled` · `readonly` · `checked` / `unchecked` / `indeterminate` · `expanded` / `collapsed` · `navigable` (leva a submenu) · `in_edit_mode` (caret) · `modified` (alterado e não salvo — muitos firmwares marcam com `*`) · `scrollable` + `has_more_above` / `has_more_below` · `obscured` (coberto por overlay) · `unknown`

Justificativa dos dois mais esquecidos: `disabled` evita que o agente gaste uma ação em item inerte; `has_more_below` evita que ele conclua que um item não existe quando ele só está fora da viewport.

---

## 8. Tipagem estrutural (L5)

Por C5, dois campos **separados**:

**`structural_type` — fato, decidível por pixels:**

`Region` · `Repeater{axis, cardinality, pitch_regularity}` · `KeyValueTable{label_band, value_band}` · `KeyValueRow` · `TextBlock` · `Rule` · `IconGlyph` · `ValueBox` · `Scrollbar` · `Overlay` (retângulo oclusivo com borda/sombra sobre conteúdo) · `LegendBand` · `TitleBand` · `Unknown`

**`semantic_hint` — hipótese, com confiança, descartável:**

`nav_menu` · `tab_bar` · `settings_list` · `help_panel` · `footer` · `dialog` · `toolbar`

Regra: `Repeater{axis: vertical}` na borda esquerda com painel irmão à direita **sugere** `nav_menu`; nunca afirma. A confirmação exige comportamento (o painel muda ao navegar) — informação que só a camada temporal ou a cognição possuem.

`KeyValueTable` merece destaque: é a estrutura mais universal do domínio (`Minimum length … 6`, `Password Check … Setup`), aparece em todo firmware, e é detectável por duas faixas verticais de alinhamento — sem nenhum conhecimento de fabricante.

---

## 9. Identidade de tela e camada temporal (L6)

### 9.1 "Qual página está aberta" é problema de conteúdo, não de cor

Recomendação explícita: **não** resolver identidade de tela pelo motor de cor. Cada tela tem vocabulário quase único, e isso já está no OCR.

`screen_fingerprint` = função estável de (conjunto normalizado de rótulos, tolerante a ruído de OCR) + (assinatura de layout: cardinalidade dos grupos, esqueleto de regiões) + (texto da faixa de título). Daí um `screen_id` estável por conteúdo, casado por vizinho mais próximo contra telas já vistas.

O IPE afirma *"esta é a mesma tela que o `screen_id` X"* e entrega o título lido. Ele **não** afirma *"esta é a aba Security"* — nomear é cognição (P2/P8). O valor de um id estável por conteúdo é grande: permite à camada de cognição construir um mapa de navegação ao longo do tempo, sem que ninguém escreva esse mapa à mão.

### 9.2 FrameBundle

O IPE opera sobre um feixe: os N quadros que compõem uma tela estável, mais o último quadro da tela **anterior**. O quadro anterior é o que habilita S7 (transição do destaque) e é barato de guardar.

| Sinal temporal | Uso |
|---|---|
| `change_mask` entre telas estáveis consecutivas | Duas regiões mudam ao navegar: de onde saiu e para onde foi ⇒ 2 candidatos em vez de 20 |
| Piscada | Caret ⇒ `in_edit_mode`; distingue cursor de conteúdo |
| Persistência entre os N quadros | Primitiva presente em 1 de 8 quadros é reflexo ou ruído, não UI |
| Correlação foco↔painel de ajuda | Corrobora foco por **conteúdo**, canal totalmente independente de cor |

Custo arquitetural em §12.

---

## 10. Contrato de saída (L7)

### 10.1 Duas visões

Uma só saída não serve aos dois consumidores: auditoria quer tudo, LLM tem custo por token.

| Visão | Consumidor | Conteúdo |
|---|---|---|
| `perception.full` | Auditoria, depuração, regressão | Todas as camadas, todas as features, toda a evidência. Gravado em `captures/` |
| `perception.digest` | Camada de cognição (LLM) | Árvore compacta: estrutura, texto, estados, confiança. Sem vetores de feature |

Ambas derivam da mesma execução; `digest` é projeção de `full`, nunca recomputação.

### 10.2 Esboço do `digest`

```json
{
  "spec_version": "0.1",
  "screen": {
    "screen_id": "sha256:9f2c…",
    "title_text": "Security",
    "quality": { "focus": 0.81, "valid_area": 0.94, "gate": "pass" }
  },
  "regions": [
    {
      "id": "r1",
      "structural_type": "Repeater",
      "axis": "vertical",
      "cardinality": 6,
      "semantic_hint": { "value": "nav_menu", "confidence": 0.72 },
      "elements": [
        { "id": "e1", "text": "Main",        "state": [] },
        { "id": "e2", "text": "Advanced",    "state": [] },
        { "id": "e3", "text": "Security",
          "state": [ { "name": "selected", "confidence": 0.93,
                       "channels": ["S1","S7"] } ] },
        { "id": "e4", "text": "Boot",        "state": [] },
        { "id": "e5", "text": "Save & Exit", "state": [] },
        { "id": "e6", "text": "Event Log",   "state": [] }
      ]
    },
    {
      "id": "r2",
      "structural_type": "KeyValueTable",
      "semantic_hint": { "value": "settings_list", "confidence": 0.88 },
      "rows": [
        { "label": "Minimum length", "value": "6",     "state": [] },
        { "label": "Maximum length", "value": "20",    "state": [] },
        { "label": "Password Check", "value": "Setup",
          "state": [ { "name": "disabled", "confidence": 0.66,
                       "channels": ["S5"] } ] },
        { "label": "Flash Write Protection", "value": "Disabled", "state": [] }
      ],
      "scroll": { "has_more_below": false, "confidence": 0.9 }
    }
  ],
  "abstentions": [
    { "scope": "r3", "reason": "classe pequena demais para estatística",
      "n_members": 2 }
  ]
}
```

Note que `abstentions` é **conteúdo**, não ausência de conteúdo (P3): a cognição precisa saber onde o motor se recusou a decidir.

### 10.3 Estabilidade

O schema é versionado (`spec_version`) e a compatibilidade importa, porque o prompt da camada de cognição depende dele. Mudança incompatível exige incremento de versão maior e revalidação do conjunto dourado.

---

## 11. Protocolo de avaliação

Sem isto, a especificação não é falsificável (C9). O motor atual já tem o instinto certo (`test_selection.py` com tabela de acurácia); falta generalizar por camada.

### 11.1 Conjuntos

| Conjunto | Verdade de referência | Papel |
|---|---|---|
| Sintético (`make_test_image.py`) | Perfeita por construção | Regressão barata; permite degradação fotométrica controlada |
| Fotos reais anotadas | Anotação manual | Realismo |
| Negativo (~240 capturas sem seleção) | Nenhuma seleção | Mede falso positivo — ~~já em uso~~ **o corpus não existe mais** (ver nota) |
| **Degradado sintético** | Herdada do sintético | Sintético + perspectiva, reflexo, desfoco, moiré simulados. **Testa L0 diretamente** |
| **Pareado HDMI/serial** (se disponível, C10) | Quase perfeita, automática | Verdade barata em escala, sem anotação manual |

> **Nota (2026-08-10)**: o conjunto negativo de ~240 capturas **não existe mais** — eram dados de sessão, nunca versionados, e foram perdidos. Sobrou 1 negativo verdadeiro (`test_bios_noselect.png`). As taxas históricas de falso positivo (39,5% → 1,4% → 2,0%) citadas aqui, em `../reference/PROCESSO_OCR.md`, em `../studies/ESTUDO_SELECAO.md` e em `test_selection.py` continuam sendo registro do que foi medido, mas **não são mais reproduzíveis nem comparáveis com medições novas**. Ver `../specs/p-specs/fixture-de-teste-nunca-versionada.md`. Reconstituir um conjunto negativo é pré-requisito para que a métrica de falso positivo deste §11.1 volte a valer.

### 11.2 Métricas por camada

| Camada | Métrica |
|---|---|
| L0 | Taxa de retificação bem-sucedida; erro de reprojeção; % de área válida |
| L1 | Precisão/cobertura de primitivas, textuais e estruturais **separadas** |
| L3 | Qualidade de agrupamento (F1 pareado ou V-measure) contra agrupamento anotado |
| L4 | Acurácia de estado, taxa de abstenção, falso positivo no conjunto negativo — **por canal (S1–S9), com ablação** |
| L5 | Acurácia de `structural_type`; calibração dos `semantic_hint` |
| L6 | Estabilidade do `screen_id`: mesma tela sob 3 iluminações e 3 ângulos ⇒ mesmo id |

Métrica de calibração de confiança (a confiança relatada bate com o acerto observado?) é tão importante quanto acurácia: confiança descalibrada engana a cognição de forma pior que erro declarado.

### 11.3 Validação com fabricante retido (obrigatória)

Calibrar em N−1 fabricantes, medir no N-ésimo **nunca visto durante a calibração**, e publicar esse número separado. É a única evidência real de independência de fabricante (C1). Uma tabela de acurácia obtida ajustando limiares nos três modelos-alvo não prova nada sobre o quarto.

---

## 12. Alternativas arquiteturais

| # | Abordagem | Prós | Contras | Recomendação |
|---|---|---|---|---|
| **A** | **CV determinística em camadas** (esta spec) | Determinística, auditável, milissegundos, sem dados de treino, evidência explícita | Agrupamento à mão é onde mora o risco; layout inédito pode exigir novo mecanismo | **Base do projeto.** Adotar |
| **B** | **A + detector de componentes treinado** (detector pequeno tipo DETR/YOLO sobre L1) | "Aprendido" ≠ "LLM": inferência determinística, rápida, roda em NPU. Generaliza a layout inédito muito melhor que regra escrita | Exige dataset anotado e disciplina de MLOps; menos auditável | **Evolução natural após A.** Não conflita com "sem VLM": não há linguagem envolvida |
| **C** | **VLM em tempo de execução** | Zero regras; lida com layout inédito | Segundos por quadro, não determinístico, sem confiança calibrada, alucina. Viola P3/P7 | **Rejeitada em runtime** — e a rejeição está correta. **Mas** vale como ferramenta *offline* de pré-anotação para construir o dataset de B, com revisão humana. Isso não coloca VLM no pipeline |
| **D** | **Casamento por template/registro de tela** | Trivialmente exato na tela conhecida | Quebra a cada revisão de firmware; é heurística por fabricante disfarçada | Só como *cache* opcional em L6, sempre com fallback para A |
| **E** | **Canal não visual** (HDMI, serial) | Elimina a maior fonte de erro | Depende de recurso do alvo; pode não existir | Não substitui A. **Usar como fonte de verdade para calibrar e validar** (§11.1) |

**Trade-off do estado temporal (C7/§9).** Adotar `FrameBundle` torna o IPE **stateful**, com custos reais: reprodutibilidade passa a depender do feixe (mitigável persistindo o feixe junto da saída — P7); a GUI e o `main.py` de imagem única deixam de ser o caminho principal; falha de alinhamento degrada o sinal (5/5 → 3/5 com tremor de 4 px, já medido). **Recomendação:** manter todos os canais temporais como **corroborantes**, jamais como única evidência. Assim o motor continua funcionando com um quadro só, e fica mais preciso quando houver contexto temporal — a degradação é graciosa em vez de catastrófica.

---

## 13. Riscos e limitações conhecidas

| Risco | Impacto | Mitigação |
|---|---|---|
| L3 agrupa errado em layout inédito | Alto — limita tudo acima (C6) | Fallback por vizinhança (§6.3); abstenção; métrica de agrupamento isolada |
| Gradiente de design confundido com gradiente de iluminação | Alto — corrompe a segmentação de região | Corrigir só escalas espaciais mais grossas que a estrutura da UI (§L0) |
| Limiares calibrados em poucos exemplos | Médio-alto | Já reconhecido para `STRIP_*` (1 exemplo real). Regra escala-livre (§7.3) + fabricante retido |
| Reflexo estático (câmera e luminária fixas) | Médio | Máscara de validade; persistência temporal não resolve reflexo *estático* |
| OCR erra o rótulo | Médio | Fingerprint tolerante a ruído; `raw_ocr` sempre presente (P5) |
| Firmware com UI gráfica moderna (mouse, animação) | Médio | Detecção de tela estável precisa de histerese; animação nunca é tela estável |
| Confiança descalibrada | **Alto** — engana a cognição silenciosamente | Métrica de calibração obrigatória (§11.2) |
| Explosão do `digest` em telas grandes | Baixo-médio | Projeção com orçamento; `full` fica em disco |
| **Entrada mais limpa piora o resultado** — com bordas duras, a caixa do OCR engole a barra de destaque e contamina L1/L3 | Médio-alto, e **latente**: dorme enquanto a entrada for foto de câmera, ativa com HDMI/VM/screenshot | Nenhuma aplicada; motor abstém em vez de chutar. Medido em 2026-08-10, correção no agrupamento tentada e rejeitada — ver `../specs/p-specs/caixa-de-deteccao-engloba-barra-de-destaque.md` |

---

## 14. Perguntas em aberto

Decisões que dependem de vocês e que mudam a especificação:

1. **Algum dos três modelos-alvo expõe saída HDMI/DP utilizável durante o POST, ou console redirection por serial?** Muda o custo de L0 e resolve §11.1 quase de graça. *Ressalva de 2026-08-10: se a resposta for sim, a adoção exige revalidar o motor contra o gabarito — entrada de bordas duras arma um teto medido (§13, última linha).*
2. **A câmera será rigidamente fixa em fixture?** Se sim, os canais temporais sobem de "corroborantes" para "primários" e vários riscos caem.
3. **Universo de firmware é fechado (3 modelos) ou aberto?** Fechado favorece A; aberto justifica investir em B mais cedo.
4. **Orçamento de latência por tela estável?** Define quanto de L1 estrutural cabe por quadro.
5. **Resolução efetiva em píxeis por caractere?** Abaixo de ~12 px de altura de caixa, as features de traço (§5.2) deixam de ser confiáveis e S4 sai do jogo.
6. **A cognição recebe o `digest` inteiro ou uma visão filtrada por tarefa?** Afeta §10 e o orçamento de contexto.
7. **Quem produz a anotação de referência, e com que ferramenta?** Sem isso, §11 não sai do papel.

---

## 15. Sequência sugerida (sem código)

| Fase | Entrega | Critério de saída |
|---|---|---|
| 0 | Respostas às perguntas de §14; congelar v1.0 desta spec | Decisões registradas |
| 1 | Ferramenta e schema de anotação; conjuntos dourados de §11.1 | Verdade de referência existe e é medível |
| 2 | L0 isolada, medida contra o conjunto degradado | Métricas de §11.2 para L0 publicadas |
| 3 | L1 estrutural (não textual) ao lado do OCR | Precisão/cobertura de primitivas por fonte |
| 4 | L3 com regiões por fundo e ritmo por eixo inferido | Métrica de agrupamento; **caso da Positivo resolvido pela raiz** |
| 5 | L4 multicanal com abstenção e confiança calibrada | Ablação por canal; falso positivo ≤ o de hoje |
| 6 | L5/L6, contrato L7 nas duas visões | Estabilidade de `screen_id`; schema congelado |
| 7 | Validação com fabricante retido | Número publicado separadamente (§11.3) |

O `selection.py` de hoje não é jogado fora: suas três decisões de medição corretas (amostragem de fundo por perímetro, tinta por percentil, teste escala-livre do vice-campeão) sobem para L2 e L4 como mecanismos, e o que muda de verdade é o que está **abaixo** delas — normalização e agrupamento, que hoje não existem.
