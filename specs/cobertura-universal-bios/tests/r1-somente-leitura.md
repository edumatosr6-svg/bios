# Testes — Restrições transversais (R1–R6)

Casos que atravessam todas as features. Rodam sem hardware.

## CT-R1.1 — `SAFE_KEYS` não foi alargada
- **Dado** `registry.SAFE_KEYS`
- **Então** ele é exatamente `{up, down, left, right, enter, esc, pageup, pagedown,
  home, end, tab}`
- (Falha se este slug adicionar qualquer tecla — é a fronteira deliberada.)

## CT-R1.2 — Nenhuma tecla de alteração em nenhum caminho novo (KPI K7)
- **Dado** cada um dos caminhos novos (F1 reader, F2 navegação, F3 tour, F4 tool)
  executado sobre a sessão fake que registra teclas
- **Então** para todos: `set(pressed) ⊆ registry.SAFE_KEYS`
- **E** `{"+", "-", "f10", "y"} ∩ set(pressed) == ∅`

## CT-R1.3 — Rotas declaradas validadas na importação
- **Dado** todo módulo novo de tool importado
- **Então** nenhum `UnsafeRoute` é levantado, e uma rota fabricada com `"f10"` levanta

## CT-R2.1 — Abstenção nunca vira valor
- **Dado** todos os casos de abstenção de `f4-find-setting.md`
- **Então** `value` é sempre `None` nesses casos, e nenhum campo do resultado carrega
  um palpite

## CT-R3.1 — Casamento só contra grafias declaradas
- **Dado** um texto de tela que não corresponde a nenhuma grafia de `labels.py`
- **Quando** qualquer caminho novo tenta casá-lo
- **Então** o resultado é abstenção/falha, não a linha mais próxima

## CT-R3.2 — Conceito não cadastrado
- **Dado** um pedido por um conceito ausente de `labels.FIELDS`/`labels.SCREENS`
- **Então** `labels.UnknownLabel` é levantado com a mensagem que instrui a editar
  `biostools/labels.py`

## CT-R4.1 — Sessão compartilhada (KPI K11)
- **Dado** F1, F2 e F4 executados em sequência
- **Quando** contamos instanciações de `BiosSession` e construções do engine de OCR
- **Então** ambas são 1
- **E** nenhum caminho novo chama `BiosSession(...)` diretamente — todos recebem a
  sessão por parâmetro
  (verificável por inspeção estática/grep nos módulos novos)

## CT-R5.1 — Leitura sempre pós-tecla e verificada
- **Dado** qualquer navegação nova
- **Então** após cada `enter`/`pagedown` há uma leitura (`read_stable`) antes de
  qualquer asserção sobre a tela
- **E** o resultado da verificação é o que decide sucesso/falha

## CT-R6.1 — `save_and_exit` inalcançável pelos caminhos novos (KPI K8)
- **Dado** F2, F3 e F4
- **Quando** qualquer um recebe `save_and_exit` como destino, pai ou entrada de índice
- **Então** o pedido é recusado, sem teclas enviadas
