# A caixa de detecção do OCR engole a barra de destaque (bordas duras)

> **Risco latente, e não hipotético.** Hoje isto só se manifesta em imagem **sintética**. A entrada real do projeto é foto de câmera, e é só por isso que o teto não morde. Se o projeto ganhar um caminho de entrada mais limpo — captura HDMI, VM, screenshot direto — **este teto ativa em produção**. É uma armadilha que só aparece depois de uma mudança que pareceria uma melhoria óbvia da qualidade de entrada.
>
> Isso importa mais do que parece porque **a captura HDMI já está proposta na arquitetura**: `../../architecture/VISUAL_FEATURE_SPEC.md` §C10 a lista como canal alternativo que "elimina perspectiva, moiré, reflexo, vinheta, desfoco, temperatura de cor", §11.1 a quer como fonte de verdade pareada, e §14 pergunta explicitamente se algum dos três modelos-alvo expõe saída HDMI utilizável no POST. Ou seja: a mudança que arma este teto é uma direção que o projeto já considera desejável, e cuja tabela de custo/risco não a mencionava até agora.

## O problema

Quando a barra de destaque da seleção tem **bordas duras** (retângulo perfeito, como em imagem gerada por software), o detector de texto do `rapidocr` não separa a barra do texto que ela destaca: a caixa delimitadora do item selecionado **engloba a barra inteira** em vez de abraçar os glifos. A caixa fica inflada, e a inflação contamina tudo que é medido a partir dela.

Observado em 2026-08-10, durante a validação de acurácia (`../../studies/estudo-motores-ocr.md`) — é o **único** caso em que `rapidocr-openvino` perde para o `paddleocr` no gabarito inteiro.

Medida: altura da caixa do item selecionado ÷ mediana das alturas dos seus pares.

| Imagem | paddleocr | rapidocr-openvino |
|---|---|---|
| `test_bios.png` (sintética) | 1.06 | **1.64 — inflada** |
| `positivo_advanced_mapt.jpg` (foto real) | 0.93 | 1.03 |
| `positivo_saveexit_save-changes.jpg` (foto real) | — | 1.10 |

A separação é limpa: em foto de câmera as bordas da barra são suaves e ruidosas, e o detector não a engole. Em imagem sintética a borda é um degrau perfeito e ele engole.

### A cadeia de falha, medida passo a passo

1. **A caixa infla.** No `test_bios.png`, o item "Main" fica com `h=36` contra `h=21-23` dos pares (grupo `g002`, eixo horizontal).
2. **O E6 separa o item dos pares.** `perception/stages/e6_equivalence.py` agrupa por lacuna: `SIZE_GAP = 0.34 × altura mediana = 7.8px`. As alturas ordenadas são 21, 21, 23, 23, 36 — o vão de 13px entre 23 e 36 está acima do limite, então **split**. O "Main" vira a classe `h:top0:size1`, de tamanho 1, `usable_as_reference=False`, e o motor abstém com `E6.equivalence too_few_members_to_compare`.
   O **alinhamento não foi o culpado**: y=116 contra 120-122 dos pares, folgado dentro de `ALIGN_GAP=16.1`. É puramente a altura.
3. **Corrigir o E6 não resolve — experimento decisivo.** Um patch em `_by_role` absorvendo singletons de tamanho na classe grande vizinha foi aplicado e **funcionou no que se propunha**: o "Main" passou a ficar numa classe de 5 membros com todos os pares, `usable=True`. **E o E7 continuou sem apontá-lo** (`no_channel_singled_out_a_member`).

### O que o experimento força a concluir

A contaminação não está só na geometria do E6 — ela chega aos **descritores do E3**. O docstring do próprio `perception/stages/e3_characterization.py` declara a premissa que a caixa inflada viola:

> *"Background is sampled from the bbox perimeter, not the whole crop. Text boxes hug their glyphs -- measured ink coverage of 51-73% on real captures"*

Quando a caixa engole a barra, o anel de perímetro amostra **a barra** em vez do fundo. O `bg_local` deixa de ler como fundo limpo, e o E7 perde exatamente o sinal que identificaria a seleção — o canal `S1_background` compara um fundo contra outro fundo, e aqui um dos dois virou a própria barra.

Confirmação independente de que o problema não é só a caixa: a altura da **tinta** do "Main" também sai inflada (31 contra ~14 dos pares). Ou seja, **nem medir o glifo em vez da caixa recuperaria o valor correto** — a segmentação de tinta dentro da caixa inflada também é contaminada.

## Onde ele mora

- **Origem**: o detector de texto do `rapidocr` (`PP-OCRv6_det_small`) — ver `../d-specs/rapidocr.md`.
- **Onde a contaminação se propaga**: `perception/stages/e3_characterization.py` (descritores de fundo e tinta medidos sobre a caixa inflada) **e** `perception/stages/e6_equivalence.py` (partição por lacuna de altura). Os dois ao mesmo tempo — é o que torna este teto diferente dos parentes listados abaixo.
- **Quem emite a abstenção**: `perception/stages/e7_state.py`, agindo corretamente com a informação que recebeu.
- Feature afetada: `../f-specs/motor-percepcao-interface.md`.

## Por que existe

Limitação do detector da dependência, não bug do pipeline. O detector de texto é treinado para achar regiões de texto; um retângulo sólido de bordas duras coladas ao texto é, para ele, parte do mesmo blob. Com bordas suaves (foto), o gradiente não sustenta o blob e a caixa volta a abraçar os glifos.

Do lado do motor de percepção, a premissa violada é explícita e está no E3: **a caixa abraça os glifos**. Todo o resto (amostragem de fundo no perímetro, segmentação de tinta, partição por altura no E6) é construído em cima dela. Quando a premissa cai, cai em cascata.

## Por que NÃO foi corrigido — resultado negativo medido

O patch do E6 descrito acima foi rodado contra o **gabarito inteiro** e **piorou**:

- seleção caiu de **8/11 para 7/11** — quebrou `positivo_advanced_hardware-monitor`, que passou de 1/1 para 0/1;
- criou um falso positivo de texto corrompido (`'mayicause syst'`) na foto AMI `20260803-154341`;
- e **nem corrigia o caso alvo** (o E7 seguiu sem apontar o "Main").

Trocaria um acerto em foto real por um caso sintético que nem chegava a ser recuperado. Registre-se como **opção tentada e medida**, não como opção não explorada: qualquer tentativa futura de mexer no `SIZE_GAP`/`_by_role` do E6 por causa deste teto tem que superar este resultado.

Nenhum código foi alterado — `perception/stages/e6_equivalence.py` está intocado.

## Como evitar / mitigar

**O comportamento atual está correto pela filosofia do projeto.** O motor se abstém com `too_few_members_to_compare` em vez de chutar, que é exatamente o que `../../architecture/PERCEPTION_PIPELINE_SPEC.md` pede (§2 "Abstenção antes de chute", e §E10 sobre abstenção como conteúdo de primeira classe — "é a diferença entre 'nada está selecionado' e 'não consegui dizer'"). O teto degrada para abstenção nomeada, não para erro silencioso.

Enquanto a entrada for foto de câmera, nada precisa ser feito. **O gatilho a vigiar é a mudança de fonte de entrada**: no dia em que entrar captura HDMI, VM ou screenshot direto, as imagens passam a ter bordas duras como as sintéticas e este teto deixa de ser hipotético. Nesse cenário, os caminhos plausíveis (nenhum implementado, nenhum medido):

- usar `--engine paddleocr` para entradas de borda dura (mede 1.06 no mesmo caso), pagando o custo de tempo;
- corrigir a caixa **antes** do E3 — encolher a bbox até a extensão da tinta antes de caracterizar. Note que a medição de tinta inflada (31 vs ~14) diz que isso não é trivial;
- atacar no E3, tornando a amostragem de fundo robusta a perímetro contaminado — é onde o sinal realmente se perde, e por isso o candidato mais promissor dos três.

O que **não** funciona, por medição: mexer no agrupamento do E6.

## Parentesco: terceira ocorrência da mesma família

É a terceira vez nesta linha de trabalho que **conteúdo de *estado* (a barra de destaque) contamina um estágio *estrutural* que roda antes do E7**:

| Teto | Estágio contaminado | Como a barra contamina | Status |
|---|---|---|---|
| `barra-destaque-cria-fronteira-de-regiao-e4.md` | E4 (regionalização) | pela **borda** de gradiente que ela desenha, lida como fronteira de contexto | Mitigado |
| `vazamento-destaque-linha-descricao-adjacente.md` | E6/E7 (classe e decisão) | pela **cor** que ela vaza para a linha vizinha | Aberto |
| este | E6 **e** E3 ao mesmo tempo | pela **caixa de detecção** que ela faz o OCR inflar | Aceito |

O padrão vale mais que os três casos isolados: o pipeline separa estrutura de estado por design, mas a barra de destaque é um objeto que é as duas coisas ao mesmo tempo — desenho na superfície e marcador de estado — e por isso vaza para cima na cadeia por qualquer canal disponível (borda, cor, caixa). Um quarto caso deve ser procurado primeiro nos estágios E3–E6, não no E7.

**Atualização 2026-08-10 — a família tem uma segunda variante.** Mais dois casos apareceram no mesmo dia, e o segundo deles obriga a alargar o enunciado:

| Teto | Estágio afetado | Relação com o marcador de estado | Status |
|---|---|---|---|
| `classe-fina-canal-unico-eleito-por-ruido.md` | E7 (decisão) | **nenhum marcador presente** — a classe é de 3 membros e um canal elege ruído como se fosse estado | Mitigado |
| `campo-focado-por-borda-sem-canal-no-e7.md` | E7 (canais) | o marcador é uma **borda**, e nenhum canal do E7 mede borda — ele **escapa** em vez de contaminar | Aberto |

Ou seja: o marcador de estado ou **vaza para os estágios estruturais** (borda→E4, cor→E6/E7, caixa→E3+E6) ou **fica invisível para os canais de estado** (anel de foco), dependendo do traço com que a interface o desenha. Nos dois lados a raiz é a mesma: ele é objeto de superfície e marcador de estado ao mesmo tempo, e o pipeline separa as duas coisas por design.

Consequência prática já registrada nos outros dois: o motivo de abstenção no contrato **não distingue** os casos da família. Aqui o motivo é `too_few_members_to_compare` (não `no_channel_singled_out_a_member`, como nos outros dois), o que ajuda um pouco — mas só até o ponto em que os dois se sobrepõem, como no experimento do patch, onde corrigir a classe fez o motivo virar `no_channel_singled_out_a_member`.

## Status

**Aceito como limite permanente enquanto a entrada for foto de câmera — 2026-08-10.** Investigado até a causa raiz, com a correção óbvia (E6) tentada, medida e **rejeitada por piorar o gabarito**. Não corrigido por decisão fundamentada, não por falta de investigação. Reavaliar obrigatoriamente se o projeto ganhar um caminho de entrada de imagem sem ruído de câmera.

### CONFIRMADO ao vivo — 2026-08-20

**Não é mais risco latente: o teto se manifestou em produção, medido, com a correção prescrita funcionando.**

Tela real da BIOS Positivo, página Advanced, capturada por HDMI a 1280x720. A olho nu a barra de destaque está claramente visível atrás de `» Trusted Computing`, e `Advanced` está destacado na barra lateral. Mesmo assim:

| Motor | Resultado | Tempo por leitura |
|---|---|---|
| `rapidocr-openvino` (default) | **abstém** — `no_channel_singled_out_a_member`, cursor indeterminado | ~0.6s |
| `paddleocr` | **acerta** — navegou 3 passos e leu `CPU Temperature: 64 C` | ~13s |

A leitura do paddleocr foi conferida contra a tela: `64 C` e `3098 RPM` conferem com o que o monitor mostrava. O `rapidocr` não errou a resposta — ele **se absteve**, que é a degradação correta pela §E10, e a camada de tools por sua vez recusou apertar tecla sem saber onde o cursor estava. Nada aconteceu de errado; simplesmente não houve resposta.

O que isso fecha e o que não fecha:
- **Fecha** a dúvida sobre se o teto ativaria com entrada de borda dura: ativa, e com a fonte que o projeto passou a usar.
- **Não fecha** a causa: a cadeia de falha medida em 2026-08-10 foi sobre imagem sintética. Que a falha ao vivo tenha exatamente a mesma raiz (caixa de detecção englobando a barra) é a hipótese mais provável, dada a coincidência de motor, de sintoma e de tipo de borda — mas não foi verificada com `--explain` neste caso.

**Desfecho (2026-08-20, no mesmo dia): a mitigação adotada não foi trocar de motor.** A camada de tools passou a ler o cursor pelo `selection.py`, que mede cor de outro jeito e enxerga o destaque com o motor rápido — 0.66s por leitura, contra 13s do paddleocr e contra o rapidocr+E7 que não vê nada (`../f-specs/camada-de-tools-consulta-bios.md`). O **`paddleocr` foi removido do projeto** logo depois, então a comparação A/B recomendada abaixo **não é mais executável num checkout limpo**; ela fica como registro. Este teto continua aberto no motor de percepção — o que mudou é que a camada de tools deixou de depender dele.

O custo da mitigação por troca de motor era real e não pequeno: com `--engine paddleocr` a mesma tool levou **63.5s** fim a fim (55s só de navegação, que faz uma leitura por tecla) contra os ~2s de partida e 0.6s por leitura do default. Trocar de motor resolve a correção às custas de sair da meta de <8s por leitura que motivou a adoção do rapidocr em primeiro lugar (`../../studies/estudo-motores-ocr.md`).

### O gatilho previsto aconteceu — 2026-08-20

**A condição que esta P-spec mandava vigiar está satisfeita.** O projeto passou a capturar a tela por **capture card USB-HDMI** em vez de câmera apontada para o monitor: sinal digital direto, sem reflexo, sem ângulo, sem desfoque óptico — ou seja, exatamente a classe de **bordas duras** que a seção "Como evitar / mitigar" nomeia como gatilho ("no dia em que entrar captura HDMI, VM ou screenshot direto (...) este teto deixa de ser hipotético").

O que **não** foi feito: nenhuma medição do teto sob HDMI. Não há evidência ainda de que ele se manifeste na prática — a mudança de entrada é recente e ainda não foi rodada contra o gabarito. O status permanece *aceito*, mas a justificativa que o sustentava ("enquanto a entrada for foto de câmera") **não vale mais**, e a reavaliação obrigatória prevista acima está pendente.

Duas coisas herdam esse risco e devem ser conferidas primeiro se algo falhar de forma estranha:
- a camada de tools nova ([`../f-specs/camada-de-tools-consulta-bios.md`](../f-specs/camada-de-tools-consulta-bios.md)), cuja navegação depende de detecção de estado correta a cada tecla;
- o default `rapidocr-openvino` ([`../d-specs/rapidocr.md`](../d-specs/rapidocr.md)), que é o motor onde o caso foi medido perder. O primeiro teste a fazer é o A/B já indicado: comparar contra `--engine paddleocr`, que mede 1.06 no mesmo caso.
