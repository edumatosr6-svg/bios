# Canal S5 (dimming → "disabled") adiado

## O problema
Um canal de estado que detectaria "desabilitado" por queda de contraste (dimming) foi implementado e depois retirado do conjunto v1 de canais de E7, porque queda de contraste é ambígua entre dois casos: um item realmente desabilitado perde contraste, mas um item que só ganhou uma barra de destaque atrás também perde contraste — o fundo muda localmente, e a diferença texto-fundo se move junto. Nas fixtures da Positivo, o canal rotulava itens genuinamente **selecionados** como `disabled`: uma resposta confiantemente errada, não uma ausência de resposta — o tipo de erro que a arquitetura trata como pior que abstenção (`../../architecture/PERCEPTION_PIPELINE_SPEC.md` §2).

## Onde ele mora
`perception/stages/e7_state.py` — a tupla `CHANNELS` só lista `S1_background`, `S2_chroma`, `S3_polarity`; a constante `DISABLED_CHANNEL_DEFERRED` documenta a decisão inline, junto com a lista `CONTRADICTORY` que trataria `{"selected", "disabled"}` como estados que não podem coexistir num mesmo elemento, caso o canal volte. Afeta a cobertura de estado descrita em `../../architecture/VISUAL_FEATURE_SPEC.md` e a feature `../f-specs/motor-percepcao-interface.md`.

## Por que existe
Foi testada a corroboração óbvia — exigir que a cor do texto também perca croma, já que acinzentar puxa a cor para neutro — e medida como não discriminante: uma barra de destaque clara atrás de texto escuro também empurra o texto pra neutro. As duas leituras (desabilitado de verdade / apenas destacado) sobrevivem ao teste, então o teste não decide nada entre elas.

## Como evitar / mitigar
Nenhuma mitigação hoje — o canal fica fora do conjunto v1 em vez de ser corrigido às pressas com mais um limiar. O sinal mais promissor para separar os dois casos é temporal (§4 de `../../architecture/PERCEPTION_PIPELINE_SPEC.md`): uma barra de destaque se move quando o operador navega; um item desabilitado não. Isso exige o caminho multi-frame, considerado escopo de v2 — hoje o motor já aceita feixes de mais de um frame (`perceive(frames=[...])`), mas E7 ainda não usa evidência temporal na decisão de estado.

## Canal ausente por outro motivo (2026-08-10)
Não confundir este caso com `campo-focado-por-borda-sem-canal-no-e7.md`. Aqui um canal **foi proposto, implementado e retirado** por ser ambíguo; lá o canal (borda/contorno) **nunca foi proposto**, e a consequência é que o campo focado da BIOS Positivo — marcado por anel de foco — é invisível para o E7. São duas lacunas diferentes no mesmo conjunto `CHANNELS`.

## Status
Aceito como limite permanente da v1 — 2026-08-06. Não é um bug pendente; é uma decisão de escopo até existir sinal temporal.
