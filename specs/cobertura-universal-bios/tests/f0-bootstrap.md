# Testes — F0: Colheita das grafias de submenu (bootstrap)

Sessão fake como nos demais arquivos. O passo humano (editar `labels.py`) não é
testável como ação; o que se testa é o **resultado** dele e a proibição de
automatizá-lo.

## CT-F0.1 — Colheita despeja texto cru sem casar
- **Dado** uma tela fake de Advanced com linhas declaradas (`"Hardware Monitor"`) e
  não declaradas (`"Trusted Computing"`, `"MAPT"`)
- **Quando** o modo `--harvest` executa
- **Então** `data/raw_labels/advanced.json` contém **todas** as linhas, inclusive as
  não declaradas
- **E** nenhuma foi descartada por não casar com `labels.py`
- (É o que quebra a circularidade: colher não exige grafia declarada.)

## CT-F0.2 — Cada linha crua carrega posição
- **Então** toda linha do dump tem `text`, `screen`, `screen_index` e `bbox`
- **E** linhas vindas de screenful diferentes têm `screen_index` diferentes

## CT-F0.3 — Colheita usa rolagem
- **Dado** uma Advanced fake com 3 screenful
- **Quando** `--harvest` executa
- **Então** o dump contém linhas com `screen_index` 0, 1 e 2
- (Sem F1, os submenus abaixo da dobra nunca seriam colhidos.)

## CT-F0.4 — Colheita não entra em submenu
- **Quando** `--harvest` executa
- **Então** nenhum `enter` foi enviado sobre um item de conteúdo
- (Ela não pode: é justamente o que ainda não sabe fazer.)

## CT-F0.5 — Colheita não escreve em `labels.py`
- **Dado** o mtime e o conteúdo de `biostools/labels.py` antes da execução
- **Quando** `--harvest` executa
- **Então** o arquivo está byte-idêntico
- (CA-F0.3: automatizar a tabela anularia a provenance.)

## CT-F0.6 — `save_and_exit` não é colhida
- **Então** não existe `data/raw_labels/save_and_exit.json`
- **E** nenhuma navegação para `save_and_exit` foi pedida

## CT-F0.7 — Somente `SAFE_KEYS`
- **Então** `set(session.pressed) ⊆ registry.SAFE_KEYS`

## CT-F0.8 — Os oito submenus alvo têm grafia declarada (KPI K13)
- **Dado** `biostools/labels.SCREENS` após o bootstrap
- **Então** existe entrada canônica para: `hardware_monitor`, `trusted_computing`,
  `device_control`, `network_stack`, `mapt`, `smart_charging`, `tls_auth`, `pap`
- **E** cada uma tem entrada correspondente em `SUBMENUS` com pai `advanced`

## CT-F0.9 — CONFIRMADO exige evidência crua (KPI K12)
- **Dado** cada entrada de `SUBMENUS` com `provenance == "CONFIRMADO"`
- **Quando** o verificador roda sobre `data/raw_labels/`
- **Então** existe ≥ 1 linha crua que casa por `screen.match_score` com alguma grafia
  daquele submenu
- **E** a contagem de CONFIRMADO sem evidência é 0
- (Falha se alguém marcar CONFIRMADO um submenu nunca visto.)

## CT-F0.10 — Palpite não precisa de evidência
- **Dado** uma entrada com `provenance == "palpite"`
- **Então** CT-F0.9 não a exige em `data/raw_labels/`
- **E** ela não conta para K6 nem K13 como confirmada

## CT-F0.11 — `data/raw_labels/` versionado (KPI K10/K6)
- **Então** `git ls-files data/raw_labels/` retorna ≥ 1 arquivo
- **E** nenhuma regra de `.gitignore` cobre o diretório

## CT-F0.12 — Ordem F0 → F3
- **Dado** um `SUBMENUS` em que nenhum submenu tem grafia declarada
- **Quando** o tour de F3 executa
- **Então** ele termina com sucesso
- **E** os submenus aparecem em `skipped` com motivo `"grafia não declarada"`
- **E** isso **não** é tratado como falha do tour
