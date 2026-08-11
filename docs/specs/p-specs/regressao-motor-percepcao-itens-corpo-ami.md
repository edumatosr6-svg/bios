# Regressão do motor de percepção em itens de corpo AMI

## O problema
Nas 5 fotos reais da Positivo (`captures/positivo_*.jpg`), o motor novo (`perception/`) supera o `selection.py` antigo em toda métrica medida (ver `../f-specs/motor-percepcao-interface.md`, seção "Coexistência"). Mas no outro modelo de BIOS já suportado (AMI, fotos `captures/20260803-1543*`), o motor novo erra os itens de corpo que o antigo acerta:

| Métrica | `selection.py` (antigo) | `perception/` (novo) |
|---|---|---|
| Item de corpo AMI correto (ex.: "ACPI Configuration") | 2/2 | 0/2 |

Já foi observado na prática, não é uma preocupação antecipada. O motor novo não é estritamente melhor que o antigo — troca uma classe de erro por outra, dependendo do modelo de BIOS.

## Onde ele mora
Afeta a feature `../f-specs/motor-percepcao-interface.md`. Os estágios mais prováveis de conter a causa são `perception/stages/e6_equivalence.py` (partição por papel estrutural — tamanho + alinhamento) e `perception/stages/e7_state.py` (decisão por razão contra o segundo colocado, canais `S1_background`/`S2_chroma`/`S3_polarity`), mas isso não foi confirmado por instrumentação — só a regressão fim-a-fim foi medida.

## Por que existe
Causa raiz não isolada nesta sessão — apenas medida, não diagnosticada. Três hipóteses razoáveis, nenhuma confirmada:

1. O agrupamento por papel estrutural (E6) ou a exigência de vencedor batendo o segundo colocado por 1.8x (`RUNNER_UP_RATIO`, E7) pode ser mais rígido do que o par piso/razão que o `selection.py` antigo calibrou especificamente para o corpo (`MIN_BG_DISTANCE=250`, distinto do piso mais permissivo usado para fileira/coluna — ver `../../studies/ESTUDO_SELECAO.md`).
2. O item de corpo da AMI (ex.: "ACPI Configuration") é sinalizado por cor de texto ("Sinal B" no vocabulário do `selection.py`), não por barra de fundo. Se o motor novo, ao combinar canais em E7, pesar `S1_background` mais que `S2_chroma` quando os dois entram em conflito ou quando um deles não dispara, isso explicaria uma queda seletiva justamente no sinal que a AMI usa.
3. **(adicionada em 2026-08-07, enfraquecida no mesmo dia)** A falha poderia estar antes do E6/E7, no E4: se a barra de destaque do item de corpo for lida como fronteira de região, o item cai sozinho numa região e o E7 fica sem pares para comparar. Esse mecanismo foi isolado, medido noutro modelo e **corrigido** — ver `barra-destaque-cria-fronteira-de-regiao-e4.md` e `../f-specs/fusao-regioes-continuidade-fronteira.md`. O A/B da correção (fusão ligada vs. desligada) deu resultado **idêntico** nas 4 fixtures `captures/20260803-1543*` — mesmas contagens de região/grupo/classe, mesmos estados, mesmas confianças. Ou seja: a regressão AMI **não** é do tipo que a fusão por continuidade de fundo resolve. Isso não exclui o E4 por completo (a fusão só age quando os dois lados da fronteira têm o mesmo fundo), mas devolve a prioridade às hipóteses 1 e 2.

## Como evitar / mitigar
Hoje: `--legacy` na GUI (ver `../f-specs/motor-percepcao-interface.md`) mantém disponível o caminho que acerta os itens de corpo AMI. Nenhuma mitigação foi implementada dentro do motor novo.

Próximo passo natural, ainda não feito: medir por canal (`S1_background` vs. `S2_chroma`) especificamente nos 2 casos de corpo AMI que regrediram, e comparar com os valores que o `selection.py` antigo usa para o mesmo caso (`../../studies/ESTUDO_SELECAO.md`, método 1 — "Estatística de cor"), antes de tocar em qualquer limiar do motor novo.

## Status
Aberto — 2026-08-06 (hipótese 3 adicionada e enfraquecida por medição em 2026-08-07). Medido, não diagnosticado, não mitigado.
