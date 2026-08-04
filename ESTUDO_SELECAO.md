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
