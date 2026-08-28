# Testes — F1: Leitura de página inteira por rolagem

Todos os casos rodam contra uma **sessão fake** (`FakeSession`) que:
- devolve uma lista pré-definida de readings, uma por posição de rolagem;
- registra toda tecla enviada em `pressed`;
- ignora `pagedown` além do último screenful e `pageup` além do primeiro
  (imitando a BIOS real, onde rolar além da ponta é inofensivo).

Nenhum caso exige hardware, exceto os marcados `[BANCADA]`.

## CT-F1.1 — Normaliza ao topo antes de mapear
- **Dado** uma página fake de 4 screenful e a sessão posicionada no screenful 2
- **Quando** o reader executa
- **Então** o resultado contém os 4 screenful, na ordem 0..3
- **E** `pressed` começa com ≥ `max_screens + 2` ocorrências de `pageup`

## CT-F1.2 — Duas execuções seguidas dão o mesmo resultado
- **Dado** a mesma página fake
- **Quando** o reader executa duas vezes em sequência na mesma sessão
- **Então** os dois resultados têm o mesmo conjunto de linhas e os mesmos
  `screen_index`
- (Regressão do bug real citado em `study_scroll_map.py`: 5 telas/73 linhas na
  primeira rodada, 1 tela/25 linhas na segunda.)

## CT-F1.3 — Fim detectado por assinatura repetida, não por contagem
- **Dado** uma página fake de 3 screenful, onde o 4º pedido devolve o mesmo conteúdo
  do 3º (fundo da página)
- **Quando** o reader executa com `max_screens=12`
- **Então** o resultado tem exatamente 3 screenful
- **E** foram enviados 3 `pagedown` (não 12)
- **E** `truncated` é False

## CT-F1.4 — Relógio ticando não impede a terminação
- **Dado** um screenful de fundo cujo único delta entre duas leituras é a linha
  `10:02:09` → `10:02:12`
- **Quando** o reader executa
- **Então** o fim é detectado e o laço para
- (Regressão da medição de 2026-08-24.)

## CT-F1.5 — Linha majoritariamente numérica fica fora da assinatura
- **Dado** as linhas `"10:02:09"`, `"3200 RPM"`, `"CPU Temperature 45 C"`
- **Quando** a assinatura estável é calculada
- **Então** `"CPU Temperature 45 C"` está na assinatura
- **E** `"10:02:09"` não está

## CT-F1.6 — Deduplicação por sobreposição
- **Dado** dois screenful consecutivos que compartilham 5 linhas idênticas
- **Quando** o reader agrega os pares rótulo→valor
- **Então** cada uma das 5 linhas aparece **uma** vez
- **E** o `screen_index` guardado é o do screenful onde apareceu primeiro

## CT-F1.7 — Barra lateral excluída
- **Dado** um reading com linhas em `bbox.left < SIDEBAR_MAX_X` (itens da sidebar) e
  em `bbox.left >= SIDEBAR_MAX_X`
- **Quando** o reader executa
- **Então** nenhuma linha da sidebar aparece no resultado
- **E** a presença dessas linhas idênticas em todos os screenful não impede a
  detecção de fim

## CT-F1.8 — Truncamento é explícito
- **Dado** uma página fake que nunca repete assinatura (20 screenful distintos)
- **Quando** o reader executa com `max_screens=12`
- **Então** o resultado tem 12 screenful, `truncated` é True
- **E** `notes` contém uma menção explícita ao truncamento
- **E** a execução termina (não há laço infinito)

## CT-F1.9 — Cobertura da página Main (KPI K5)
- **Dado** uma fixture derivada da medição real da página Main: 73 linhas únicas
  distribuídas em 3+ screenful de ~31 linhas
- **Quando** o reader executa
- **Então** o resultado agrega 73 linhas únicas
- **E** uma leitura de screenful único sobre a mesma fixture devolve ≤ 31

## CT-F1.10 — Toda posição carrega `screen_index`
- **Dado** qualquer página fake
- **Quando** o reader executa
- **Então** toda entrada com informação posicional (bbox) tem `screen_index` não-nulo
- (Falha esperada se alguém armazenar coordenada nua.)

## CT-F1.11 — Somente `SAFE_KEYS`
- **Dado** qualquer página fake
- **Quando** o reader executa
- **Então** `set(session.pressed) ⊆ registry.SAFE_KEYS`
- **E** `"+"`, `"-"`, `"f10"`, `"y"` não aparecem

## CT-F1.12 — Página vazia / sem linhas de conteúdo
- **Dado** uma página fake cujo painel de conteúdo não tem nenhuma linha
- **Quando** o reader executa
- **Então** o resultado é vazio, com `ok=False` e erro descritivo — não uma exceção

## CT-F1.13 `[BANCADA]` — Medição ao vivo da Main
- **Dado** a máquina alvo (Positivo, BIOS 2.22.0058) na página Main
- **Quando** o reader executa
- **Então** ≥ 73 linhas únicas são mapeadas e o fim é detectado sem truncamento
