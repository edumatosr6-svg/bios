# Testes — F3: Índice de rótulos da máquina

Dois níveis:
- **Tour com sessão fake** — prova a mecânica e as invariantes de segurança sem
  hardware.
- **Validador de esquema puro** — roda sobre o `data/label_index.json` realmente
  commitado, no CI, sem hardware nem câmera.
- `[BANCADA]` — captura real.

## CT-F3.1 — Caminho do artefato é fixo e versionado (KPI K10)
- **Dado** o repositório
- **Quando** o CI executa a checagem
- **Então** `data/label_index.json` está rastreado pelo git
- **E** não está coberto por nenhuma regra de `.gitignore`
- **E** tem ≥ 1 entrada
- (Regressão de `docs/specs/p-specs/fixture-de-teste-nunca-versionada.md`.)

## CT-F3.2 — Esquema de entrada completo
- **Dado** o índice commitado
- **Quando** o validador roda
- **Então** toda entrada tem `label` não vazio, `page`, `screen_index` inteiro ≥ 0,
  `value` (str ou null) e `provenance`
- **E** todo `PageRecord` tem `page_id` único, `screen`, `submenu` (canônico ou null),
  `total_screens` ≥ 1 e `signatures`

## CT-F3.2a — `pages` torna P2 executável a partir do disco
- **Dado** o índice commitado
- **Então** para todo `PageRecord`, as chaves de `signatures` são exatamente
  `0..total_screens-1`
- **E** toda `LabelEntry.page` referencia um `page_id` existente
- **E** toda `LabelEntry.screen_index` é `< pages[page].total_screens`
- (Sem isso F4 não sabe quantos `pageup` enviar nem contra o que verificar.)

## CT-F3.2b — Referência de página quebrada é rejeitada
- **Dado** um índice fixture com uma entrada cujo `page` não existe em `pages`
- **Então** o validador falha nomeando a entrada

## CT-F3.2c — `screen_index` fora do alcance é rejeitado
- **Dado** uma entrada com `screen_index: 5` numa página com `total_screens: 3`
- **Então** o validador falha

## CT-F3.2d — `signatures` incompleto é rejeitado
- **Dado** um `PageRecord` com `total_screens: 3` e `signatures` só para `0` e `1`
- **Então** o validador falha

## CT-F3.3 — Entrada sem `screen_index` é rejeitada (KPI K9)
- **Dado** um índice fixture com uma entrada sem `screen_index`
- **Quando** o validador roda
- **Então** ele falha nomeando a entrada ofensora

## CT-F3.4 — Entrada sem provenance CONFIRMADO é rejeitada
- **Dado** um índice fixture com `provenance: "palpite"`
- **Quando** o validador roda
- **Então** ele falha
- (O tour nunca grava material inventado.)

## CT-F3.5 — Coerência submenu↔pai
- **Dado** um `PageRecord` com `submenu: "hardware_monitor"` e `screen: "boot"`
- **Quando** o validador roda
- **Então** ele falha (o pai declarado de `hardware_monitor` é `advanced`)

## CT-F3.5a — Submenu `palpite` não é visitado (CA-F2.1a)
- Ver `f2-submenus.md` CT-F2.12b. O tour registra `"provenance=palpite"` em `skipped`.

## CT-F3.6 — Cabeçalho presente
- **Dado** o índice commitado
- **Então** ele tem `bios_model`, `bios_version` (`"2.22.0058"`), `captured_at` ISO,
  `visited` não vazio e `skipped`

## CT-F3.7 — `save_and_exit` nunca visitada (KPI K8)
- **Dado** o tour rodando contra a sessão fake com todas as telas disponíveis
- **Quando** o tour termina
- **Então** nenhuma navegação para `save_and_exit` foi solicitada
- **E** nenhuma entrada do índice tem `screen == "save_and_exit"`
- **E** `skipped` contém `save_and_exit` com motivo explícito

## CT-F3.8 — Somente `SAFE_KEYS` no tour inteiro (KPI K7)
- **Dado** o tour completo sobre a sessão fake
- **Quando** ele termina
- **Então** `set(session.pressed) ⊆ registry.SAFE_KEYS`
- **E** nenhuma de `"+"`, `"-"`, `"f10"`, `"y"` aparece em `pressed`

## CT-F3.9 — Uma única sessão (KPI K11)
- **Dado** o tour completo, com `BiosSession` instrumentada para contar
  instanciações
- **Quando** ele termina
- **Então** a contagem é exatamente 1
- **E** o modelo de OCR foi construído no máximo uma vez

## CT-F3.10 — Falha isolada não aborta o tour
- **Dado** uma sessão fake em que a navegação para `security` sempre falha
- **Quando** o tour executa
- **Então** ele termina com sucesso
- **E** `skipped` contém `security` com o motivo
- **E** as demais telas foram visitadas e produziram entradas

## CT-F3.11 — Submenu inalcançável entra como pulado
- **Dado** uma Advanced fake sem a linha `"Trusted Computing"`
- **Quando** o tour executa
- **Então** `skipped` contém `{screen: advanced, submenu: trusted_computing, reason:
  ...}` e o tour continua

## CT-F3.12 — Rolagem aplicada a cada página
- **Dado** telas fake com múltiplos screenful
- **Quando** o tour executa
- **Então** entradas com `screen_index > 0` existem para cada tela multi-screenful
- (Prova que o tour usa F1 e não uma leitura única.)

## CT-F3.13 — Índice ausente é erro claro, não crash
- **Dado** que `data/label_index.json` não existe
- **Quando** o leitor de índice é chamado
- **Então** ele levanta/retorna um erro nomeado instruindo rodar o tour

## CT-F3.14 `[BANCADA]` — Captura real
- **Dado** a máquina alvo
- **Quando** o tour executa
- **Então** o índice resultante cobre todas as telas de topo menos `save_and_exit`,
  ≥ 8 submenus, e passa o validador de esquema
- **E** o arquivo é commitado
