# `Fields(scroll=True)` desistia de rolar antes de achar campos que existiam de verdade

## O problema

`registry.Fields`, quando `scroll=True`, pressiona `scroll_key` até achar todos os campos pedidos ou concluir que a página parou de mudar. **O critério de "a página parou de mudar" estava errado duas vezes seguidas**, e as duas vezes fizeram a tool desistir de campos que estavam de verdade na tela, só um pouco mais abaixo — não em fixture, em hardware real (Positivo, BIOS `1.2.5.XD22.I219V.P`, 2026-08-31).

Sintoma medido: rodando `ec_info`, `product_info`, `memory_info`, `mac_address`, `management_engine_info` e praticamente toda tool de Security/Boot/Advanced que dependia de rolagem, a resposta era `"rótulo 'X' não está nesta tela"` para um campo que estava visível a olho nu, alguns segundos de rolagem adiante.

## Onde ele mora

`biostools/registry.py`, `Fields.read()` (o laço de rolagem) e, pela mesma causa, `AllFields._scroll_and_merge()`.

## Por que existia — três causas, encontradas em sequência

**1. `stall_limit` fixo em 2, menor que a zona morta real de qualquer página.** Medido ao vivo pressionando `down` na tela Main e comparando o texto lido a cada frame: os **dois primeiros** `down` não mudam nada visível (só o relógio ao vivo) — a página só começa a rolar de verdade no terceiro. Um `stall_limit` de 2 desiste exatamente na borda dessa zona morta, uma tecla antes de funcionar.

**2. A zona morta não tem o mesmo tamanho em toda página.** Depois de corrigir para `stall_limit=4` (cobrindo a zona morta do Main com folga), o mesmo teste em Boot mostrou uma zona morta de **6** — `PXE Boot after Wake on LAN` só aparece no 8º `down`. Um limite tunado pra Main derrubava Boot antes de chegar lá.

**3. O sinal de "tem coisa nova" olhava estreito demais.** Mesmo com `stall_limit=8`, `virtualization_status`/`boot_device_integrity` ainda perdiam campo em Advanced. Causa: o laço original só contava como "progresso" (a) o campo específico pedido aparecer, ou, na segunda versão, (b) um novo *par* rótulo→valor aparecer via `screen.field_pairs`. Nenhum dos dois sinais é o mesmo que "a página está rolando" — `data/label_index.json` já mostrava por que: várias seções de Advanced são blocos longos de **texto de ajuda** (ex. a descrição de `Intel VT-d`) que rolam, mudam de conteúdo, mas nunca formam um par rótulo→valor porque não têm nada à direita. Rolando por um desses blocos, o sinal (a) e o sinal (b) ficam iguais por várias telas seguidas — parecem "parou", mas a página está andando.

Confirmado como causa raiz: `Intel VT-d` chegou a casar contra uma linha de prosa ("Enable/Disable support to Intel VT-d (Intel Virtualization Technology for Directed I/O)...") sem valor à direita, e a implementação original tratava "achei mas sem valor" como definitivo — o spec saía da lista de pendências mesmo a resposta de verdade ainda não tendo aparecido.

## Como foi corrigido

- `stall_limit` (novo campo em `Fields`/`AllFields`, default 8) e `max_scroll` (30) — folga medida acima da pior zona morta observada, não a zona morta exata; o teto duro continua sendo `max_scroll`, então um campo genuinamente ausente ainda custa um número finito de teclas, só mais generoso que antes.
- O sinal de progresso trocou de "par novo" para **texto bruto da tela inteira** (`page.content_lines`, o mesmo texto que qualquer `Field` já lê, só comparado como conjunto entre frames). Rolar por um bloco de prosa conta como progresso porque o texto muda, mesmo sem formar par nenhum.
- Um spec que casa mas não tem valor à direita **só é tratado como definitivo quando `scroll=False`**. Com `scroll=True`, esse casamento é descartado e o spec continua na lista de pendências — a resposta de verdade pode estar num frame seguinte.

Cada uma das três causas tem cobertura na suíte offline (`test_biostools.py`, `test_fields_scroll_finds_specs_past_the_first_screenful` e `test_all_fields_scroll_merges_pages`), com dublês que reproduzem especificamente a zona morta medida e o caso "prosa rola sem formar par".

## Status

**Resolvido — 2026-08-31, contra hardware real.** Todas as tools que dependiam de rolagem foram revalidadas ao vivo depois da correção (ver o F-spec [`camada-de-tools-consulta-bios.md`](../f-specs/camada-de-tools-consulta-bios.md), seção Status). `AllFields` recebeu o mesmo `stall_limit`/`max_scroll` mais generosos por consistência, mas **não** recebeu a correção #3 (sinal de texto bruto) — `goto_screen` e `main_info` continuam usando o sinal de pares. Não reproduziu o mesmo sintoma na validação de hoje, mas não foi estressado contra um bloco de prosa tão longo quanto o de Advanced; se `goto_screen` um dia relatar campo ausente que rolagem deveria alcançar, esta é a primeira suspeita.
