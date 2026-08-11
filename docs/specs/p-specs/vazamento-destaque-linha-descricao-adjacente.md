# Vazamento de destaque para linha de descrição adjacente (submenu)

## O problema
Quando um item de menu tem uma linha de descrição logo abaixo (padrão de submenu da BIOS Positivo), a barra de destaque numa foto real não fica perfeitamente contida na caixa delimitadora apertada do OCR — ela "vaza" um pouco para a linha vizinha. Essa contaminação já estava documentada no caminho antigo (`selection.py`), com um caso onde o item real e sua descrição empatavam quase exatamente em distância de fundo (`d_bg=122.2` vs. `d_bg=121.5` — ver `../../studies/ESTUDO_SELECAO.md`, seção "Limitação conhecida: item de submenu com descrição colada embaixo"). Ela **reapareceu no motor novo** (`perception/`), numa captura ao vivo real feita depois da validação com as fixtures fixas, com uma manifestação em dois lados: um falso positivo em outro item e um falso negativo no item certo, na mesma tela.

Caso observado (`captures/20260806-145050_auto.json`), fora do conjunto de 5 fotos Positivo já medido em `../f-specs/motor-percepcao-interface.md`:

- **Falso positivo**: "Smart Charging" marcado como selecionado por engano. Confiança 0.502, só o canal `S2_chroma` disparou, com magnitude 3.024 — no limite mínimo (`MIN_DEVIATION = 3.0`, `perception/stages/e7_state.py`). Causa provável: ruído de compressão/antialiasing numa classe extremamente uniforme (11 itens de corpo do painel, variação de cor típica entre eles de ~0.4 unidades) — o mesmo tipo de situação que motivou o `NOISE_FLOOR` do E7 (ver `../f-specs/motor-percepcao-interface.md`), só que aqui a magnitude ficou perto do piso, não abaixo dele.
- **Falso negativo**: "MAC Address Pass-Through (MAPT)", o item realmente selecionado, não foi marcado — abstenção `no_channel_singled_out_a_member`. Recálculo manual: o canal `S1_background` de fato detectou a MAPT com desvio forte (7.28, bem acima do piso de 3.0) — mas a linha de descrição logo abaixo ("Configure MAC Address Pass-Through to USB Docking Station") também teve o fundo anômalo (desvio 5.64), pelo mesmo vazamento de barra. A razão exigida entre vencedor e segundo colocado é 1.8x (`RUNNER_UP_RATIO`); a razão real foi só 1.29x — abaixo do limiar, então o canal não declara vencedor nenhum.

## Onde ele mora
`perception/stages/e6_equivalence.py` (papel estrutural, E6) e `perception/stages/e7_state.py` (decisão por razão, E7). Afeta a feature `../f-specs/motor-percepcao-interface.md`. A mesma limitação estrutural, na forma como se manifesta no caminho antigo, está documentada em `../../studies/ESTUDO_SELECAO.md`.

## Por que existe
Causa raiz estrutural: o rótulo do item de menu (altura ~17px) e sua linha de descrição (altura ~15px) caem na MESMA classe de equivalência em E6, porque a diferença de altura é pequena demais para disparar a separação por tamanho (`SIZE_GAP = 0.34` × altura mediana do grupo, em `perception/stages/e6_equivalence.py`). Isso permite que o vazamento de cor da descrição "compita" na mesma classe contra o item real.

O resultado é mais seguro que o do caminho antigo — abstenção em vez de detecção errada — mas ainda incompleto: a MAPT simplesmente não é encontrada. Vale registrar que é a MESMA limitação de fundo já conhecida (vazamento de destaque em foto real contaminando a linha de descrição vizinha), reaparecendo num motor diferente com uma consequência diferente, não um achado isolado novo.

## Como evitar / mitigar
Nenhuma correção aplicada — a captura que revelou isso veio depois da validação com fixtures, e a decisão foi registrar o número exato em vez de ajustar limiar às cegas (mesmo princípio descrito em `../../studies/ESTUDO_SELECAO.md`, seção "Por que threshold-chasing tem limite"). Hoje o sistema reage abstendo (`no_channel_singled_out_a_member`) em vez de chutar — ver o princípio de abstenção-antes-de-chute em `../../architecture/PERCEPTION_PIPELINE_SPEC.md` §2 ("Abstenção antes de chute").

Caminho de correção mais provável, ainda não implementado: separar rótulo e linha de descrição em classes de equivalência distintas em E6 por um critério mais forte que altura absoluta — por exemplo posição relativa dentro do grupo (a descrição está sempre imediatamente abaixo do rótulo, nunca ao lado) — em vez de tentar afinar `SIZE_GAP`.

## Teto vizinho, mesma família (suspeita, 2026-08-07)
`barra-destaque-cria-fronteira-de-regiao-e4.md` descreve outro caso em que a barra de destaque quebra o motor, e produz a **mesma** abstenção `no_channel_singled_out_a_member`. **Provavelmente não é a mesma raiz**: aqui o item selecionado está na classe com seus pares e o problema é o segundo colocado contaminado (razão 1.29x); lá o item nem chega a entrar numa classe com pares, porque o E4 o isolou numa região só dele.

**Atualização 2026-08-07**: aquele teto foi mitigado no E4 (fusão de regiões por continuidade de fronteira, `../f-specs/fusao-regioes-continuidade-fronteira.md`). A correção age sobre a **borda** que a barra desenha, não sobre a **cor** que ela vaza — este teto aqui continua aberto e sem relação com aquela mudança. Reforça a leitura de que as raízes são distintas.

O que os dois compartilham é anterior ao estágio: a barra de destaque é **conteúdo de estado** contaminando estágios **estruturais** que rodam antes do E7 — aqui pela cor que ela deposita na linha vizinha, lá pela borda de gradiente que ela desenha. Consequência prática: o motivo de abstenção registrado no contrato não distingue os dois casos, então diagnosticar um deles pelo log exige olhar a atribuição primitiva→região antes de concluir.

**Terceira ocorrência da família (2026-08-10)**: `caixa-de-deteccao-engloba-barra-de-destaque.md` — a barra contamina por um terceiro canal, a **caixa de detecção do OCR**, atingindo E3 e E6 ao mesmo tempo. Com três casos por três canais distintos (borda, cor, caixa), o padrão deixa de ser coincidência: a barra de destaque é simultaneamente desenho de superfície e marcador de estado, e vaza para cima na cadeia por qualquer canal disponível. A tabela comparativa das três está naquela P-spec.

**Quarta e quinta ocorrências (2026-08-10)**: `classe-fina-canal-unico-eleito-por-ruido.md` (canal único elegendo ruído em classe de 3 membros — mitigado) e `campo-focado-por-borda-sem-canal-no-e7.md` (o marcador de foco é uma borda e nenhum canal do E7 mede borda — aberto). A segunda alarga a família: além de o marcador **contaminar** estágios estruturais, ele pode **escapar** de todos os canais de estado. Tabela consolidada em `caixa-de-deteccao-engloba-barra-de-destaque.md`, seção "Parentesco".

**Nota de escopo (2026-08-10)**: este teto **não** foi tocado pela validação de acurácia daquela data. Ela mediu `positivo_advanced_mapt.jpg` e ali a razão de altura da caixa saiu normal (1.03), ou seja, aquele caso é de vazamento de **cor**, não de caixa inflada — os dois permanecem independentes.

## Status
Aberto — 2026-08-06 (revisado 2026-08-07 com a referência ao teto vizinho de E4; e 2026-08-10 com a terceira ocorrência da família). Falso positivo (Smart Charging) e falso negativo (MAPT) observados na mesma captura ao vivo; não corrigido.
