# Campo focado marcado por borda: nenhum canal do E7 mede contorno

## O problema
No painel de conteúdo da BIOS Positivo, o campo focado **não é marcado por preenchimento** — é marcado por uma **borda**. Recorte ampliado da tela mostra que a caixa do campo focado tem borda **dupla e mais clara** (anel de foco) contra borda simples e fina das vizinhas.

Os três canais do E7 medem preenchimento e cor:

| Canal | Descritor | O que mede |
|---|---|---|
| `S1_background` | `bg_local` | cor do fundo local |
| `S2_chroma` | `ink_chroma` | cromaticidade da tinta |
| `S3_polarity` | `contrast_polarity` | polaridade do contraste |

**Nenhum mede borda/contorno.** O marcador de foco desse nível da interface simplesmente não tem canal que o veja, e o que o motor mede nessas classes é o resíduo fotográfico ao redor do sinal verdadeiro.

Consequência prática medida em 2026-08-10, ao vivo: **mesma tela, capturas diferentes, respostas diferentes**. Numa captura, o motor acertou o campo focado (`Standard`); noutra captura da mesma tela, perdeu o `Standard` e apontou `Off` e `Enabled` (dois falsos positivos). Nada mudou na tela nem no código entre as duas.

### Evidência no `--explain`
- `S3_polarity` dá **0.00 para todos os membros de todas as classes** nessas telas — canal morto ali, não contribui com nada.
- `S2_chroma` aponta para itens **diferentes** do `S1_background` dentro da mesma classe: em `c004` o S2 elege `Enabled` enquanto o S1 elege `Off`.

Canais que discordam sobre qual membro se destaca, num painel onde um membro **de fato** está destacado, é a assinatura de que nenhum dos dois está vendo o sinal verdadeiro — cada um está rankeando ruído à sua maneira. É a leitura descrita no docstring de `perception/explain.py`: classe em que todo mundo fica num desvio parecido e o vencedor raspa no limiar é o motor achando *alguma coisa* na ausência do marcador que a interface realmente usa.

## O desfecho da pendência do `'Standard'` (fechada aqui)
`../f-specs/fusao-regioes-continuidade-fronteira.md` deixou em aberto, desde 2026-08-07, se o `selected: 'Standard'@0.82` num `settings_list` era falso positivo — o frame se perdeu antes da checagem. Verificado em 2026-08-10, com duas conclusões e **nenhuma** é a que se supunha:

1. **Não tinha relação com a fusão de regiões do E4.** Rodado com e sem a fusão, resultado **idêntico** nos frames ao vivo novos.
2. **O `'Standard'` não era falso positivo.** O recorte ampliado mostra o anel de foco duplo naquela caixa: ele *era* o campo focado, e o motor tinha acertado.

O problema real não é aquele acerto, é que ele **não se repete**: a mesma tela, capturada de novo, produz resposta diferente. Não havia bug para corrigir naquele frame; havia um canal faltando o tempo todo.

## Onde ele mora
- **Causa**: o conjunto de canais `CHANNELS` em `perception/stages/e7_state.py` — os três canais v1 medem superfície preenchida e cor de tinta.
- **Onde aparece**: classes de `settings_list` no painel de conteúdo da Positivo (dropdowns e campos de valor). **Não** afeta o `nav_menu` — ver escopo abaixo.
- Feature afetada: `../f-specs/motor-percepcao-interface.md`. Diagnosticado com `../f-specs/view-explicacao-da-decisao.md`.

## Por que existe
Limitação inerente do conjunto de canais v1, não bug. O E7 foi desenhado com canais separados exatamente porque interfaces diferentes marcam o mesmo estado por meios diferentes — uma inverte o fundo, outra recolore o texto, uma terceira apaga o resto. A lista v1 cobre os três meios que aparecem por **preenchimento e cor**; o quarto meio, **anel/contorno de foco**, é comum em campos de formulário e não foi coberto. O motor não erra o raciocínio: ele erra por não ter o instrumento.

O `S5` (dimming → `disabled`) já havia sido adiado por outro motivo (`canal-dimming-disabled-adiado.md`). Este é um caso diferente: não é um canal ambíguo que foi deixado de fora, é um canal que nunca foi proposto.

## Como evitar / mitigar
**Não corrigido.** Hoje o sistema reage se abstendo em vez de errar, o que é o comportamento correto pela §E10 de `../../architecture/PERCEPTION_PIPELINE_SPEC.md` (abstenção é conteúdo de primeira classe; "nada está selecionado" e "não consegui dizer" são coisas diferentes). Isso é consequência da regra de classe fina implementada no mesmo dia (`classe-fina-canal-unico-eleito-por-ruido.md`): ela derruba os falsos positivos que apareciam nessas classes — mas **não resolve este teto**, porque não devolve o campo focado. O saldo é errar menos, não acertar mais.

**Direção não implementada e não medida**: um **canal de borda/contorno no E7** — um descritor no E3 que meça a borda do entorno da caixa (presença, espessura, luminância do anel em relação à mediana da classe) e um canal `S4_border` que o consuma com a mesma regra escala-livre dos demais (razão contra a dispersão da própria classe, leave-one-out). Enquanto ele não existir, o campo focado nessa BIOS é **não detectável**, e nenhum ajuste de limiar muda isso.

Cuidado ao implementar: a caixa do OCR abraça os glifos, não a moldura do campo (premissa declarada no docstring de `perception/stages/e3_characterization.py`). Um canal de borda precisa amostrar **fora** da bbox, o que é território onde a caixa inflada de `caixa-de-deteccao-engloba-barra-de-destaque.md` também morde.

## Escopo: o que é confiável e o que não é
A distinção importa e não deve ser achatada em "o motor não funciona":

- **Menu de navegação (`nav_menu`): sólido.** Validado ao vivo em quatro seleções distintas (Security, Boot, Main, Boot de novo), sempre com confiança **0.76–0.91**.
- **Campo focado dentro do painel de conteúdo: não confiável**, pelo motivo acima.

São dois níveis de seleção na mesma tela. Um é detectável nesta BIOS, o outro não é — enquanto não houver canal de borda.

## Parentesco: a família continua
É mais uma ocorrência da família registrada em `caixa-de-deteccao-engloba-barra-de-destaque.md` ("Parentesco") e em `barra-destaque-cria-fronteira-de-regiao-e4.md`, mas de uma variante diferente. Nos casos anteriores o marcador de estado **contaminava** um estágio estrutural (borda virando fronteira no E4, cor vazando para o vizinho no E6/E7, caixa inflada no E3+E6). Aqui o marcador **escapa** de todos os canais de estado: ele não vaza para onde não devia, ele não chega onde devia.

O que une as duas variantes é o mesmo fato estrutural: o marcador de estado é um objeto de superfície, e o pipeline separa superfície de estado por design — então ou ele vaza para os estágios estruturais, ou ele fica invisível para os canais de estado, dependendo de com que traço a interface o desenha.

## Status
**Aberto — 2026-08-10.** Diagnosticado até a causa (canal ausente, não limiar mal ajustado), com evidência ao vivo em `captures/20260810-153155_bench_live.png` e `captures/20260810-153639_bench_live.png` (desta vez os frames **existem em disco**; ainda não commitados — ver `fixture-de-teste-nunca-versionada.md` para o precedente de evidência ao vivo perdida). Nenhuma correção aplicada; o motor se abstém.
