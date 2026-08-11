# Estudo: como o programa enxerga texto selecionado

Comparação de 5 métodos para detectar qual item de menu está selecionado. Todos medidos contra o mesmo gabarito, para a escolha ser por medição e não por opinião.

Reproduzir:

```bash
py -3.13 study_selection_methods.py
```

```bash
py -3.13 study_temporal.py
```

## Gabarito usado

| Conjunto | O que é | Como a seleção aparece |
|---|---|---|
| 3 telas sintéticas | Geradas por `make_test_image.py` | Barra de fundo invertida |
| 3 fotos de BIOS AMI real | `captures/20260803-1543*` | Cor do texto (branco vs azul) |
| ~240 capturas | Fotos diversas sem BIOS | Nenhuma — tudo marcado é falso positivo |

> **Ressalva de reprodutibilidade (2026-08-10)**: o conjunto de ~240 capturas negativas **não existe mais** (dados de sessão, nunca versionados), e uma das 3 fotos AMI (`captures/20260803-154414`) nunca foi commitada. Todas as taxas de falso positivo deste estudo continuam sendo registro do que foi medido em 2026-08-04, mas não são reproduzíveis a partir de um clone nem comparáveis com medições novas. Ver `../specs/p-specs/fixture-de-teste-nunca-versionada.md`.

## Resultados

| Método | Sintético (barra) | BIOS real (cor de texto) | Falsos positivos |
|---|---|---|---|
| **1. Estatística de cor** (atual) | **3/3** | **3/3** | **1,39%** |
| 2. Inversão de luminância | 2/3 | 2/3 | 1,70% |
| 3. Faixa de linha inteira | 1/3 | 0/3 | 2,35% |
| 4. Detecção geométrica de barra | 2/3 | 0/3 | 3,00% |

O método 5 (temporal) usa vídeo em vez de foto única, então é medido separadamente:

| Condição simulada | Acertos |
|---|---|
| Ideal (frames idênticos) | 5/5 |
| Ruído de sensor leve | 4/5 |
| Ruído + tremor de 1px | 4/5 |
| Ruído + tremor de 2px | 4/5 |
| Ruído + tremor de 4px | 3/5 |

---

## Os métodos, e o que cada um enxerga

### 1. Estatística de cor — o que está no `selection.py` hoje

Combina dois sinais: fundo invertido atrás do texto, e cor de texto que destoa das outras linhas da mesma tela (medido contra a dispersão delas, não contra um valor fixo).

**Vence em todas as métricas.** É o único que acerta as duas formas de marcação.

### 2. Inversão de luminância — "o texto é mais claro ou mais escuro que o fundo?"

Ignora matiz completamente: só olha se o texto é mais claro ou mais escuro que seu próprio fundo, e procura a linha que discorda da maioria.

**Vale registrar: o sinal em si é impecável.** Nos sintéticos, a linha selecionada aparece com polaridade `-191` contra `+240` de todas as outras — separação absoluta. Nas fotos reais, `+45` contra `-118`.

Ele reprovou por dois motivos, nenhum deles do princípio em si:
- Nos sintéticos, o tema escuro tem 2 linhas na mesma barra, e meu limite de "no máximo 1 linha" descartou as duas.
- Numa das fotos reais, essa BIOS tem **duas regiões com polaridades opostas por design** (barra de menu escura em cima, corpo claro embaixo). O método assume polaridade única na tela inteira.

Por ignorar cor, ele é o mais promissor para generalizar aos **2 modelos de BIOS que ainda não vimos** — desde que agrupado por região da tela.

### 3. Faixa de linha inteira

Em vez da caixa justa do texto, compara faixas horizontais atravessando a tela toda, apostando que a barra de seleção é mais larga que as palavras.

**Pior desempenho.** A faixa inteira inclui outras colunas e elementos, o que dilui o sinal em vez de reforçá-lo.

### 4. Detecção geométrica da barra

Procura a barra como **forma** — um retângulo sólido preenchido — via detecção de regiões uniformes, em vez de raciocinar sobre cores.

Pega barras razoavelmente bem, mas é **estruturalmente cego** para seleção marcada por cor de texto: 0/3 nas fotos reais, porque ali não existe barra nenhuma para encontrar.

### 5. Diferença temporal — enxergar a seleção **se mover**

Os quatro anteriores olham uma foto e precisam deduzir qual item parece especial. Este usa informação que hoje **descartamos**: a câmera observa continuamente, e quando o operador navega, o destaque pula de uma linha para outra. As únicas partes da imagem que mudam são a linha que ele deixou e a linha onde chegou.

Isso não depende de paleta, de polaridade, nem de existir barra — funciona em qualquer BIOS.

Dois frames dão dois candidatos (de onde saiu, para onde foi); decidir qual é o atual precisa de um desempate, feito por um método de foto única — mas escolher entre 2 candidatos é muito mais fácil que entre 20 linhas.

**É o sinal mais forte quando os frames se alinham, e o primeiro a degradar quando não se alinham** (5/5 → 3/5 com tremor de 4px). Na fábrica, porém, a câmera será fixa e montada rigidamente, então o alinhamento real deve ser bem melhor que o tremor que simulei.

---

## Recomendações

1. **Manter a estatística de cor como método principal.** É o único que cobre as duas formas de marcação hoje conhecidas, e tem a menor taxa de falsos positivos.

2. **Adicionar a inversão de luminância como sinal complementar, agrupada por região da tela.** O princípio é sólido e independente de paleta; agrupar as linhas por contexto visual (barra de menu vs corpo) resolveria a falha observada. Isso é seguro para os modelos de BIOS que ainda não conhecemos.

3. **Usar a diferença temporal como confirmação quando houver frames consecutivos.** Câmera fixa na fábrica favorece muito esse método. Vale validar com hardware real antes de confiar.

4. **Descartar faixa de linha inteira e detecção geométrica** como métodos principais — o primeiro é fraco, o segundo é cego para metade dos casos.

Um sexto caminho não foi testado: **modelo de visão** (Qwen-VL na NPU), perguntando diretamente "qual item está selecionado?". Exigiria baixar o modelo (`lemonade pull qwen3vl-it-4b-FLM`, ~3.9GB) e seria muito mais lento que os métodos acima (segundos por frame contra milissegundos), mas não precisaria de nenhuma regra escrita à mão. Vale considerar se aparecer um modelo de BIOS que os métodos de cor não deem conta.

---

## Questão de produto — resolvida (2026-08-03)

As fotos reais revelaram que **"selecionado" tem mais de um nível**: em `20260803-154341`, a aba **"Advanced"** está ativa no menu superior *e* o item **"ACPI Configuration"** está focado no corpo da tela. Ambos são destaques legítimos, com significados diferentes.

**Decisão:** reportar os dois, ao mesmo tempo, distinguidos por um campo `region` em cada linha (`"menu_strip"` ou `"body"`), em vez de conceitos separados na saída.

A causa raiz de só detectar um dos dois não era falta de rótulo — era **comparar tudo contra o fundo da tela inteira**. A barra de menu tem uma cor de fundo diferente do corpo, então *todo* item da barra (selecionado ou não) parecia "diferente" da tela inteira; só comparar cada item contra os outros itens da mesma barra isola quem está de fato selecionado ali.

Implementado em `selection.py`: as linhas são agrupadas em fileiras por posição vertical; uma fileira com pelo menos 4 itens curtos vira uma "menu strip" e é julgada contra si mesma (piso + razão em relação ao segundo colocado, em vez de distância absoluta — populações pequenas não têm amostra suficiente pra estatística de dispersão); o resto continua sendo julgado contra a tela inteira, como antes.

Resultado (`test_selection.py`): os dois níveis detectados simultaneamente na mesma foto (`Advanced [menu_strip]` + `ACPI Configuration [body]`), sintéticos 3/3 mantidos, falso positivo em 1,9% (subiu de 1,4% — o preço de ganhar esse segundo sinal).

**Ressalva de confiança:** os limiares da `menu_strip` (piso 60, razão 2,2, mínimo de 4 itens) foram calibrados contra **um único exemplo real** de barra de menu. Revisar quando os outros 2 modelos de BIOS estiverem disponíveis.

---

## Segundo modelo real (Positivo) — menu vertical, não horizontal (2026-08-04)

O usuário fotografou 5 telas de uma **BIOS Positivo** real (segundo modelo distinto que vemos, depois da AMI) — menu numa coluna vertical à esquerda (Main/Advanced/Security/Boot/Save & Exit/Event Log) em vez da barra horizontal da AMI. Resultado inicial: **0 de 9 seleções genuínas detectadas.** Toda a lógica de "menu_strip" só reconhecia fileira horizontal; um menu em coluna caía inteiro em `body` e era comparado contra a tela toda, do mesmo jeito que já tinha falhado com a AMI antes da correção anterior.

### O que foi generalizado

**Agrupamento por coluna, além de fileira.** Medindo a geometria real: itens do mesmo menu variam só 4-46px no `x0`, contra 400-2000px de distância entre colunas diferentes (barra lateral / lista de submenu / ícones à direita). O mesmo algoritmo de agrupamento por vão (`_cluster_1d`) que já existia pra fileira (vão no Y) foi reaproveitado pro eixo X.

**Divisão por continuidade, não aceitar/rejeitar.** A primeira versão rejeitava o grupo inteiro se UM vão interno fosse grande demais — descartando também a parte boa. Ex: título + rótulos + dica de atalho de teclado compartilham a mesma margem esquerda (mesma "coluna" por X), mas título e atalho ficam longe verticalmente dos rótulos do meio. `_split_by_gaps` divide em sub-sequências contíguas em vez de aceitar ou rejeitar o grupo todo.

**Gap medido fim-a-início, não início-a-início.** "Boot" (estreito) e "Security" (largo) ficam colados com ~20px de espaço real, mas ~100-200px de distância início-a-início só por causa da largura da própria palavra. Comparar fim de um item com início do próximo isola o espaço visual de verdade.

**Limiar de fundo (sinal A) diferente pra corpo vs. fileira/coluna.** A mesma constante (`MIN_BG_DISTANCE=250`) era usada nos dois contextos. Seleções reais em grupos locais pequenos mediram `d_bg` entre 75-146 — bem abaixo de 250, mas também bem acima do que qualquer item não-selecionado no mesmo grupo mediu (<26). Novo `STRIP_MIN_BG_DISTANCE=100`, só pra fileira/coluna; o corpo manteve 250.

**"Só o mais forte vence" também no sinal A.** Antes só o sinal B (cor de texto) tinha essa disciplina. Com o limiar de fundo mais permissivo, ruído de foto real passou a fazer múltiplas linhas baterem o piso ao mesmo tempo — agora o sinal A também exige vencedor claro sobre o segundo colocado.

### Resultado final (`test_selection.py`)

| Item | Status |
|---|---|
| Barra lateral (Advanced / Save & Exit) | **4 de 5 fotos** — 1 com sinal fraco (foto específica, ângulo/exposição), documentado, não exigido |
| Item de submenu (MAC Address, Hardware Monitor, CPU Overheat, Save Changes) | **1 de 4** — ver limitação abaixo |
| Falso positivo (~240 capturas negativas) | 2,0% (subiu de 1,4% — preço de detectar coluna vertical também) |
| Sintéticos + AMI (re-rotulados) | continuam 100% corretos |

**Descoberta de rotulagem:** a lista de itens de configuração da própria AMI (CPU Configuration, IDE Configuration, ... ACPI Configuration) TAMBÉM é uma coluna vertical de itens parecidos — só não tinha nome antes porque "coluna" não existia como conceito. Ela virou `menu_column` em vez de `body`, sem mudar qual linha é detectada. `body` agora significa especificamente "item isolado, não faz parte de uma lista grande o bastante" — mais raro do que antes, de propósito.

### Limitação conhecida: item de submenu com descrição colada embaixo

Na lista de submenu da Positivo, cada item tem uma linha de descrição logo abaixo (ex: "MAC Address Pass-Through (MAPT)" seguido de "Configure MAC Address Pass-Through..."). Numa foto real, a barra de destaque branca não preenche perfeitamente a caixa delimitadora apertada do OCR — a borda "vaza" um pouco pra linha vizinha. Medido num caso: o item real teve `d_bg=122.2`, e sua PRÓPRIA descrição (contaminada pelo vazamento) teve `d_bg=121.5` — praticamente empatados. A regra de "vencedor precisa bater o segundo colocado por 2,2x" corretamente se recusa a escolher entre os dois quase-iguais, então nenhum dos dois é marcado.

Não tentei consertar isso às cegas — precisa de mais fotos reais desse padrão específico (item+descrição colados) pra calibrar com confiança. O sinal A (barra lateral) não sofre desse problema porque os itens da barra lateral não têm descrição colada embaixo.

### Por que threshold-chasing tem limite

Ao longo dessa investigação, cada ajuste de limiar pra resolver um caso specific revelou um caso novo: primeiro o `std` (ruído de compressão), depois o piso de distância de fundo, depois múltiplos vencedores no sinal A, depois uma fileira espúria por coincidência de posição, depois a métrica de vão errada, depois um grupo que precisa dividir em vez de rejeitar. Em algum ponto — aqui, quando restou 1 foto com sinal fraco e 3 com vazamento de vizinhança — baixar mais o limiar geral custava mais em falso positivo do que valia pra esses casos específicos. Documentar como limitação conhecida, com o número exato medido, é mais honesto do que ficar ajustando até "parecer que passou".
