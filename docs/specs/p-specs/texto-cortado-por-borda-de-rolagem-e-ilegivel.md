# Texto cortado pela borda de rolagem do painel é ilegível — e votação não corrige

## O problema
Quando uma linha de texto da BIOS fica **parcialmente cortada pela borda de rolagem do painel de conteúdo**, o OCR lê algo estável e errado, e nenhum recurso de captura ou de corroboração recupera a leitura.

Caso real observado em 2026-08-14, na BIOS Positivo, aba Main rolada (`../../studies/estudo-votacao-ocr-multi-frame.md`): o alvo de gabarito `"Range of Years may vary."` falhou em **10 de 10 rodadas, nas duas configurações testadas** (`ocr_votes=1` e `ocr_votes=3`). Investigado recortando e ampliando a região: **a metade superior das letras não existe na tela capturada** — a linha está fisicamente cortada pela borda do painel rolável. O OCR lê consistentemente:

```
lido:     "kange or vears may vary."
esperado: "Range of Years may vary."
```

R→k, of→or, Years→vears: exatamente o que se espera de glifos com o topo amputado.

**O ponto que generaliza, e é o motivo desta P-spec existir**: isso é degradação **estável**, não ruído. Idêntica em todo frame. Um erro estável é invisível para qualquer mecanismo que funcione comparando frames — votação remove o que varia, nunca o que é igual em todos eles. Mesmo princípio que já vale para o glare em `glare-moire-degradam-ocr-captura-ao-vivo.md`, mas por causa diferente: lá a informação está apagada por luz, aqui está recortada por geometria de UI.

## Onde ele mora
Entrada do pipeline, antes de qualquer estágio de percepção — a informação já chega incompleta na foto. Afeta diretamente:
- `../f-specs/corroboracao-ocr-multi-frame.md`: define o **teto de acurácia** que a votação pode atingir. Nas 10 rodadas do estudo, o teto atingível era 310/320 e não 320/320 por causa deste único alvo; ignorá-lo faria a votação parecer ter 96.9% de acerto quando na prática ela acertou **100% do que era possível acertar**.
- Qualquer leitura de conteúdo de painel rolável em que o usuário parou a rolagem numa posição intermediária.

## Por que existe
A BIOS renderiza o painel de conteúdo com clipping: uma linha meio rolada é desenhada pela metade, não escondida inteira. A câmera captura fielmente o que a tela mostra — não há nada errado com a captura nem com o motor de OCR. O texto simplesmente **não está inteiro na origem**.

Não é limitação do `rapidocr-openvino` (`../d-specs/rapidocr.md`): nenhum motor lê glifos cuja metade superior não foi desenhada. `../../studies/estudo-motores-ocr.md` já estabeleceu que os motores candidatos empatam em acurácia sobre o gabarito formal — trocar de motor não move este teto.

## Como evitar / mitigar
- **Ao montar gabarito**: não incluir linhas cortadas pela borda de rolagem como alvos, ou incluí-las declarando que são teto conhecido. Caso contrário, todo placar de acurácia carrega um erro fixo que mascara o que está sendo medido — foi o que quase aconteceu no estudo da votação.
- **Ao capturar**: rolar o painel até que a linha de interesse esteja inteira antes de ler. É correção de operação, não de software.
- **Não** esperar correção de votação, de mais frames, de mais resolução ou de troca de motor. Nenhum deles ataca a causa.
- O sistema hoje **não detecta** essa condição: lê `"kange or vears may vary."` com confiança alta e segue adiante, sem abstenção nem aviso. Isso é uma lacuna frente ao princípio de abstenção-antes-de-chute (`../../architecture/PERCEPTION_PIPELINE_SPEC.md` §2).

  **Investigado em 2026-08-14 (sessão seguinte à criação desta spec), sobre nova captura ao vivo da mesma câmera/tela/alvo (`p004`, `{x:413, y:91, w:126, h:18}`, confiança 0.9435): as duas abordagens geométricas mais óbvias e baratas foram testadas e nenhuma produz sinal confiável.**

  1. *Altura da caixa como outlier no grupo rítmico*: `p004` pertence a `g001` (eixo vertical, pitch ≈35px, 15 membros), alturas `18(cortada), 23, 18, 17, 17, 21, 19, 16, 20, 20, 19, 22, 23, 16, 20`. 18 cai bem no meio da distribuição (16–23) — não é outlier por nenhum limiar razoável, e um filtro por "altura menor que os vizinhos" geraria falso positivo constante em linhas curtas legítimas (várias outras do grupo têm altura igual ou menor), sem sequer pegar o caso real.
  2. *Perfil vertical de intensidade de tinta dentro da caixa* (espaço Lab, canal L — mesmo espaço dos descritores `ink_color`/`bg_local` de `perception/stages/e3_characterization.py`), comparando o desvio máximo por linha de pixel contra o fundo local: `p004` cortada (h=18, fundo≈43.0) mostra silêncio nas primeiras ~5 linhas, subida abrupta na linha 5, plateau forte nas linhas 6–14 (pico 131 na linha 9), queda nas linhas 15–17. `p008` normal ("System Time", h=23, fundo≈63.0) mostra a **mesma forma relativa**: silêncio nas primeiras ~6 linhas, subida na linha 6, plateau nas linhas 7–19 (pico 157 na linha 12), queda nas linhas 20–22. Não há a assimetria esperada ("tinta só na metade inferior, silêncio total na metade superior") que separaria visualmente uma caixa cortada de uma completa. Interpretação: o motor de OCR ajusta a caixa à tinta de fato visível, então mesmo lendo só a metade inferior de cada glifo a caixa já vem enquadrada nessa metade — não sobra "vazio no topo" que denuncie o corte. A caixa se adapta ao dano em vez de expor geometricamente que ele aconteceu.
  3. *Descartada sem chegar a medir*: casar a altura do corte com uma borda estrutural (`structural:rules`, `RuleSource` em `perception/stages/e2_extraction.py`). Não há régua nenhuma perto de y≈89–91 nesta captura (as detectadas ficam em y=234, 235, 501, 503, 504, 526, 527, 529). O limite de corte é um `overflow`/scroll clip que a BIOS não desenha como linha — não é um painel com moldura visível, então não há sinal estrutural para casar.

  Detectar esse modo de falha de forma genérica exigiria analisar a *forma* dos glifos (reconhecer que um "k" tem contorno anômalo para ali dever ser "R") — um projeto de reconhecimento de forma de caractere, desproporcional para este único modo de falha. Direção tentada e descartada com evidência; não é mais lacuna não-explorada.

## Status
Aceito como limite permanente do que a votação pode corrigir — 2026-08-14. Não corrigido e não detectado pelo motor. As duas mitigações geométricas mais óbvias (outlier de altura; perfil de tinta) foram investigadas e descartadas com evidência em 2026-08-14 (sessão seguinte); a correção continua sendo operacional (rolar antes de capturar), não de software. Documentado para que placares de acurácia futuros o desconte explicitamente em vez de o diluírem.
