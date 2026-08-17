# Estudo: votação multi-frame de OCR (`ocr_votes`) contra leitura única, ao vivo

Data: **2026-08-14**, captura ao vivo real.

## Pergunta

A feature `ocr_votes` (`../specs/f-specs/corroboracao-ocr-multi-frame.md`) foi implementada e validada **só logicamente** — não regride confiança, vota certo entre uma leitura boa e uma degradada. Faltava a pergunta que importa: **votar entre frames do mesmo estado de tela parado lê melhor que ler uma vez só, em captura ao vivo de verdade?** E, se lê, quanto custa.

A hipótese vinha de uma observação, não de uma medição: a mesma frase saiu `"Version"` numa captura e `"Versian"` em outra, minutos depois, da mesma tela parada (`../specs/p-specs/glare-moire-degradam-ocr-captura-ao-vivo.md`). Se boa parte dos erros de caractere é ruído instável entre frames, votar deveria removê-los.

## Ambiente e metodologia

- Câmera UGREEN 4K a 1280x720 (`../specs/d-specs/webcam-ugreen-4k.md`), apontada para uma BIOS **Positivo**, aba **Main já rolada** (System Time / Intel BIOS Guard Technology / BIOS Version / EC Build Date / etc.).
- **Índice 0 do OpenCV** — e não o índice que a listagem de câmeras rotula como UGREEN. Ver "Achado colateral" no fim.
- Script ad-hoc de investigação, **não versionado** (ver "Reprodutibilidade" abaixo).
- **10 rodadas.** Em cada rodada: captura de **uma** rajada de 5 frames (8 frames de warmup descartados), e as duas configurações rodam **sobre exatamente a mesma rajada**.
- Gabarito: **32 strings** lidas a olho de um frame de referência salvo. Pontuação por **casamento exato**: a string do gabarito aparece na lista de primitivos simbólicos lidos. 10 rodadas × 32 alvos = **320 alvos por configuração**.
- Configurações: `ocr_votes=1` (comportamento antigo, leitura única) contra `ocr_votes=3` (votação). Um teste anterior de 3 rodadas incluiu também `ocr_votes=5`.

**Por que as duas configurações rodam sobre a mesma rajada — é a decisão metodológica central deste estudo.** Capturar uma rajada separada para cada configuração mediria também o ruído entre momentos diferentes da câmera, que é exatamente o que a votação existe para atacar. Misturar as duas coisas responderia à pergunta errada ("uma captura foi mais sortuda que a outra?") em vez da pergunta feita ("dada a mesma evidência bruta, votar extrai mais que ler uma vez?").

**Por que o relógio ficou fora do gabarito.** O campo `System Time` (valor `15:19:04` no frame de referência) foi **deliberadamente excluído** dos 32 alvos: ele muda a cada segundo, então divergência ali seria a tela mudando, não erro de leitura. Contá-lo produziria falha garantida em ambas as configurações e diluiria o placar com um caso que não mede nada.

## Resultados brutos

| Configuração | Acertos | % | Tempo médio |
|---|---|---|---|
| `ocr_votes=1` (leitura única) | 306/320 | 95.6% | **5.9s** |
| `ocr_votes=3` (votação) | 310/320 | 96.9% | **11.3s** |

Lidos assim, os números parecem dizer "1.3 ponto percentual de ganho por 2x de custo" — e essa é a leitura errada.

## A leitura correta: existe um teto, e ele é 310

Um dos 32 alvos, **`"Range of Years may vary."`**, é **estruturalmente impossível de ler** com este enquadramento, e falhou **10/10 nas duas configurações**. Investigado recortando e ampliando a região: a linha está **fisicamente cortada pela borda de rolagem do painel da BIOS** — a metade superior das letras não existe na tela capturada. O OCR lê consistentemente `"kange or vears may vary."` (R→k, of→or, Years→vears).

Isso é degradação **estável**: idêntica em todo frame, não ruído. **Nenhuma votação pode corrigir**, pelo mesmo princípio que já vale para o glare em `../specs/p-specs/glare-moire-degradam-ocr-captura-ao-vivo.md` — votar entre frames remove o que varia, nunca o que é igual em todos eles. Detalhe do caso em `../specs/p-specs/texto-cortado-por-borda-de-rolagem-e-ilegivel.md`.

Descontado esse alvo, o **teto atingível é 310/320**, e o placar vira outra coisa:

| Configuração | Contra o teto (310) | Rodadas no teto |
|---|---|---|
| `ocr_votes=3` | **310/310 — 100%** | **10 de 10** |
| `ocr_votes=1` | 306/310 | 6 de 10 |

Ou seja: **a votação bateu o teto em todas as rodadas**, e a leitura única saiu com **ao menos um erro de leitura em 40% das capturas**.

### Os 4 erros que a leitura única cometeu, e que a votação corrigiu

A votação corrigiu **4 de 4 — nenhum sobrou**:

| String do gabarito | Rodadas em que `votes=1` errou |
|---|---|
| `7.2.4.XD22CPG7.I219V.P` (versão da BIOS) | 2 e 8 |
| `EC Build Date (MM/DD/YYYY)` | 4 e 9 |

São exatamente o tipo de erro **instável entre frames** que motivou a feature — nunca o mesmo erro em duas rodadas seguidas. Confirma na prática a hipótese que veio da observação `"Version"`/`"Versian"`.

## Custo: ~2x mais lento, e isso estoura a meta de <8s

5.9s → **11.3s**. `estudo-motores-ocr.md` estabelece **<8 segundos por leitura** como requisito explícito do projeto — a razão de o motor de OCR ter sido trocado. **`ocr_votes=3` não cabe nesse requisito.**

É uma troca real de precisão contra tempo de resposta, e quem for adotar `ocr_votes=3` como default precisa decidir conscientemente sobre esse requisito, não herdá-lo quebrado. **Nenhuma mudança de default foi feita nesta medição** — `ocr_votes=1` continua o padrão no código.

## `ocr_votes=5` não se justifica: o ponto ideal medido é 3

Num teste anterior de 3 rodadas, `votes=3` e `votes=5` **empataram** — ambos 93/96, ambos no teto em todas as rodadas — e o `votes=5` custou **16.1s contra 11.2s** do `votes=3`. Dois votos a mais não compraram nada de acurácia e custaram ~45% de tempo. O ponto ideal medido é **3**.

## Ressalvas — todas precisam ficar explícitas

1. **Condições melhores que as das capturas de 2026-08-12.** As duas P-specs de captura ao vivo (`../specs/p-specs/glare-moire-degradam-ocr-captura-ao-vivo.md`, `../specs/p-specs/retificacao-e1-inatingivel-sem-moldura-visivel.md`) analisaram fotos com **bem mais glare**; a câmera foi reposicionada entre aquela sessão e esta. O moiré continua visível. Como havia **menos ruído disponível para a votação corrigir**, é plausível que o ganho seja maior sob condições piores — **mas isso não foi medido e não deve ser afirmado como fato**.
2. **Uma única tela de BIOS.** Positivo, Main rolada, um enquadramento. Não é um conjunto variado de telas/modelos. A conclusão vale para **esta tela e este enquadramento**.
3. **n=3 não era suficiente.** Um teste anterior com 3 rodadas deu diferença de **apenas 1 caso** entre as configurações — dentro do ruído. Foi preciso ir a **n=10** para o resultado se separar. Qualquer replicação futura deve começar de n=10, não de n=3.
4. **Casamento exato de string** é uma métrica dura: não distingue "errou um caractere" de "não leu nada". Serve para esta pergunta (a votação removeu o erro ou não), mas não mede quão perto ficou.

### Reprodutibilidade

O script que produziu estes números é **ad-hoc e não versionado**, e nem os frames capturados foram salvos além do frame de referência do gabarito. **Estes números não são reproduzíveis a partir de um clone** — uma nova rodada teria que reconstruir script e gabarito. Mesma classe de problema já registrada em `../specs/p-specs/fixture-de-teste-nunca-versionada.md` e na ressalva de reprodutibilidade de `estudo-motores-ocr.md`.

## Conclusões

1. **A votação funciona, e o ganho é maior do que o placar bruto sugere**: 100% do atingível em 10 de 10 rodadas, contra 40% das capturas da leitura única saindo com ao menos um erro. O número honesto não é "95.6% → 96.9%", é "**4 de 4 erros corrigíveis, corrigidos**".
2. **A hipótese de origem se confirma**: os erros que a votação corrige são instáveis entre frames (`7.2.4.XD22CPG7.I219V.P`, `EC Build Date (MM/DD/YYYY)`, nunca o mesmo erro duas rodadas seguidas) — a mesma assinatura de `"Version"`/`"Versian"`.
3. **Degradação estável continua fora de alcance**, por construção. `"Range of Years may vary."` falhou 10/10 nas duas configurações e falharia com qualquer número de votos.
4. **O custo é o problema aberto, não a acurácia.** 2x de tempo estoura a meta de <8s. A decisão de default fica em aberto e é uma decisão de produto, não de medição.
5. **3 votos, não 5.**

## Achado colateral: o rótulo de câmera aponta para o índice errado

Durante a preparação da medição, `python -m perception.run --list-cameras` mostrou `0: Integrated Camera` e `1: UGREEN Camera 4K`, mas na prática o índice **0** é a UGREEN apontada para a BIOS e o **1** é a webcam integrada. Seguir o rótulo abriu a webcam apontada para a pessoa em vez da câmera da BIOS. Registrado com causa e consequência em `../specs/p-specs/rotulo-de-camera-desalinhado-do-indice-opencv.md`.
