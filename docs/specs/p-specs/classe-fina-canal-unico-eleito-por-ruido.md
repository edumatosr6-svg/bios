# Classe fina: um canal sozinho elege ruído como "selecionado"

## O problema
Numa classe de equivalência pequena (3 membros, o mínimo que o E6 deixa passar como usável), um único canal do E7 pode cruzar os dois limiares de decisão — `MIN_DEVIATION = 3.0` e `RUNNER_UP_RATIO = 1.8` — sem que exista qualquer diferença real entre os membros. O motor então reporta um `selected` com confiança de aparência normal, e nada no contrato distingue esse caso de uma detecção legítima.

Observado ao vivo em 2026-08-10, tela de **Boot** da BIOS Positivo (`captures/20260810-153639_bench_live.png`). O motor reportava três estados: `Boot` (correto, `nav_menu`) e mais `Off` e `Enabled` (ambos errados, em `settings_list`).

| Caso | Classe | Vencedor | Desvio | 2º colocado | Veredito |
|---|---|---|---|---|---|
| Três dropdowns com o texto **literalmente idêntico** — "Enabled", "Enabled", "Enabled" | 3 membros | um dos "Enabled" | **6.16** | 3.15 | passou nos dois limiares **sem nada que distinguisse os membros** |
| Três dropdowns, foco real em `Standard` | 3 membros | `Off` (**errado**) | 10.04 | `Standard` 3.44 | elegeu o membro errado |
| Seleção genuína da mesma tela | **6 membros** | correto | **31.07** | — | sinal real, uma ordem de grandeza acima |

O primeiro caso é o mais gritante e o que fecha o diagnóstico: três valores de texto idêntico não têm como ter um "destacado" — o que o canal mediu foi ruído.

## Onde ele mora
`perception/stages/e7_state.py` — a regra de decisão por razão contra a dispersão da própria classe, com estimativa por leave-one-out. Afeta a feature `../f-specs/motor-percepcao-interface.md`. Foi diagnosticado com `../f-specs/view-explicacao-da-decisao.md` (`--explain`), que é o que expõe o desvio de **todos** os membros em vez de só o do vencedor.

## Por que existe
Limitação inerente da estatística, não bug pontual e não propriedade de nenhuma interface.

Todo número do E7 é uma razão contra a dispersão da própria classe, e o leave-one-out estima essa dispersão a partir dos **outros** membros. No tamanho mínimo de classe (3), isso é uma mediana e um desvio calculados sobre **dois valores** — uma estimativa sem poder nenhum, que qualquer ruído fotográfico domina. Os limiares não protegem contra isso: eles são razões, e uma razão contra um denominador mal estimado cruza limiar com facilidade.

## Hipótese descartada por medição — registre, porque o gatilho intuitivo está errado
A formulação natural do problema é "exigir corroboração quando a classe é **uniforme**", com uniformidade medida pela dispersão caindo no piso de ruído (`NOISE_FLOOR = 1.5`). **Não discrimina:**

| Classe | Dispersão medida | Abaixo do `NOISE_FLOOR`? |
|---|---|---|
| `nav_menu` — a detecção **correta** | 0.67 | sim |
| "Enabled"×3 — o **ruído** | 0.50 | sim |

As duas estão abaixo do piso. Essa regra teria matado o acerto junto com o erro. Foi o `--explain` que mostrou isso antes de a regra ser implementada — sem ele, ela teria sido escrita e teria *parecido* funcionar no frame de teste.

## Como foi mitigado
**Implementado em 2026-08-10**: `MIN_SIZE_FOR_SINGLE_CHANNEL = 4` em `perception/stages/e7_state.py`. Abaixo de 4 membros, um canal sozinho não basta — um **segundo canal independente** precisa concordar antes de o motor afirmar o estado.

O gatilho é o **tamanho da classe**, não a uniformidade: o fundamento não é sobre interface, é sobre confiabilidade da estatística, e o tamanho da amostra é exatamente o que determina essa confiabilidade. "Dois canais concordando vale mais que um canal apontando duas vezes" já era o padrão declarado do motor (§F4 de `../../architecture/PERCEPTION_PIPELINE_SPEC.md`, e o docstring do próprio E7) — a regra o torna **obrigatório exatamente onde a evidência é mais rala**, em vez de introduzir uma constante nova calibrada contra alguma população.

A rejeição não some: gera abstenção nomeada `single_channel_on_thin_class`, com elemento, estado, tamanho da classe, mínimo exigido e quais canais falaram — visível no `--explain` e no contrato, conforme §E10 (abstenção é conteúdo de primeira classe).

### Validação (A/B com `MIN_SIZE_FOR_SINGLE_CHANNEL` em 0 vs. 4, mesmo processo)
- **Gabarito completo** via `study_ocr_engines.py --accuracy`, dois motores — **zero regressão medida**:

| Motor | Texto | Seleção | Inesperados | Com e sem a regra |
|---|---|---|---|---|
| `paddleocr` | 14/15 | 11/15 | 1 | **idêntico** |
| `rapidocr-openvino` | 15/15 | 9/15 | 0 | **idêntico** |

  (Denominador 15 é o recorte do próprio script, que soma `sidebar` + `submenu` — ver a nota em `../../studies/estudo-motores-ocr.md` sobre por que ele não reproduz literalmente a tabela `11/11`, `8/11` daquele estudo.)
- **Frame ao vivo `captures/20260810-153639_bench_live.png`** (Boot): os dois falsos positivos sumiram; sobra `Boot` conf 0.91.
- **Frame ao vivo `captures/20260810-153155_bench_live.png`** (Main): `Main` conf 0.90 com dois canais concordando, inalterado.

## O que a regra NÃO resolve
Ela faz o motor **se abster** onde antes errava — que é o comportamento correto pela §E10 — mas não recupera nenhuma detecção. Nas telas em que o marcador de foco é uma **borda**, o campo focado continua não detectável, porque nenhum canal do E7 mede borda: ver `campo-focado-por-borda-sem-canal-no-e7.md`. Os dois documentos descrevem o mesmo episódio por lados diferentes — aqui, por que o motor dizia algo errado; lá, por que ele não consegue dizer o certo.

## Status
**Mitigado — 2026-08-10.** Regra implementada, medida em A/B contra o gabarito completo com dois motores (zero regressão) e contra dois frames ao vivo. Sem teste automatizado, como o resto do motor.
