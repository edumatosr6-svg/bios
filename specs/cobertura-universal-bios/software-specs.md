# cobertura-universal-bios — Software Specs

## Visão geral

Hoje o sistema só responde com confiança as perguntas que têm uma **tool nomeada**
escrita para elas (`cpu_temperature`, `bios_info`, `main_info`, `main_menu`). Fora
dessa lista, o caminho genérico (`goto_screen`) cobre pouco: lê só o que está visível
sem rolar, só alcança as telas da barra lateral (`navigate.TOP_LEVEL_SCREENS`), e
depende de dicas escritas à mão para adivinhar em qual tela procurar.

Este slug inverte a relação: **qualquer pergunta sobre a BIOS da máquina sob teste
deve ser respondida — ou honestamente recusada — exista ou não uma tool nomeada para
ela.** Três mecanismos entregam isso: leitura de página inteira por rolagem (F1),
alcance genérico a submenus (F2), um índice de rótulos colhido de hardware real (F3),
e a tool `find_setting` que costura os três (F4).

O sistema permanece **somente leitura** e **abstencionista**: nunca casar com a linha
mais parecida, nunca alargar `registry.SAFE_KEYS`, nunca visitar `save_and_exit`.

### Restrições transversais (valem para toda feature abaixo)

- **R1 — Somente leitura.** Nenhum código deste slug pode enviar tecla fora de
  `registry.SAFE_KEYS` (`up, down, left, right, enter, esc, pageup, pagedown, home,
  end, tab`), nem alargar esse conjunto. Um pedido de escrita ("desliga o Fast Boot")
  deve ser recusado com mensagem explícita de fronteira deliberada.
- **R2 — Abstenção é conteúdo de primeira classe.** Resposta confiantemente errada é
  pior que ausência de resposta (`docs/architecture/PERCEPTION_PIPELINE_SPEC.md` §2).
- **R3 — Rótulos declarados, nunca adivinhados.** Todo casamento de texto passa por
  `screen.match_score` contra grafias declaradas em `biostools/labels.py`. Proibido
  fallback para "a linha mais parecida".
- **R4 — Uma sessão serve muitas tools.** Nada aqui abre câmera nem carrega modelo de
  OCR por chamada; tudo recebe a `BiosSession` já quente (`biostools/session.py`).
- **R5 — Verificação após tecla.** Toda leitura é confirmada contra o que a tela
  mostra *depois* da tecla, nunca assumida.
- **R6 — `save_and_exit` nunca é visitada** por nenhum caminho automático deste slug.

---

## Features

### F0 — Colheita das grafias de submenu (bootstrap)

**Descrição.** F2 precisa de uma grafia declarada para achar um submenu; R3 proíbe
declarar grafia não vista em hardware real; F3 precisa de F2 para visitar o submenu.
Essa circularidade é real e precisa de um passo próprio para ser quebrada.

Verificado no código: `biostools/labels.SCREENS` hoje declara apenas `main, advanced,
security, boot, save_and_exit, event_log` e `hardware_monitor`. **Sete dos oito
submenus citados em `descriptions.md`** (Trusted Computing, Device Control, Network
Stack, MAPT, Smart Charging, TLS Auth, PAP) **não têm grafia declarada**, e sem elas
o KPI K6 é inatingível.

F0 quebra a circularidade usando o procedimento que `biostools/labels.py` já
descreve na sua própria docstring: colher os rótulos **crus** que a percepção
extraiu de telas reais, propor offline a correspondência conceito↔grafia, **revisão
humana**, e só então colar na tabela. Nunca roda no caminho quente.

O passo de colheita **não precisa de grafia declarada**: ele lê a página de Advanced
inteira com F1 e despeja todo texto do painel de conteúdo, sem casar nada.

**Critérios de aceite**
- CA-F0.1 — Existe um modo de colheita (`study_label_index.py --harvest`) que navega
  às telas de topo (menos `save_and_exit`), executa F1 e escreve **todo** texto cru
  do painel de conteúdo em `data/raw_labels/<screen>.json`, sem casar contra
  `labels.py` e sem entrar em nenhum submenu.
- CA-F0.2 — Cada linha crua registra `text`, `screen`, `screen_index` e `bbox`.
- CA-F0.3 — A colheita **não escreve em `biostools/labels.py`**. A edição da tabela é
  ato humano, revisado — automatizá-la anularia a disciplina de provenance.
- CA-F0.4 — Ao final deste slug, `labels.SCREENS` contém entrada para cada um dos
  oito submenus alvo, e cada grafia efetivamente vista em `data/raw_labels/` está
  marcada `# CONFIRMADO -- Positivo, <data>`; grafias não vistas, se incluídas como
  previsão, ficam **sem** a marca CONFIRMADO.
- CA-F0.5 — Um teste verifica que, para cada submenu declarado com provenance
  CONFIRMADO em `SUBMENUS`, existe ao menos uma linha em `data/raw_labels/` que casa
  com uma das suas grafias por `screen.match_score`. Provenance CONFIRMADO sem
  evidência crua correspondente reprova.
- CA-F0.6 — `data/raw_labels/` é **versionado** (mesma regra do índice, K10).
- CA-F0.7 — F0 usa exclusivamente teclas de `registry.SAFE_KEYS` e não visita
  `save_and_exit`.

**Ordem obrigatória:** F0 (colheita + revisão humana de `labels.py`) precede F3. Rodar
o tour antes de F0 produz um índice sem submenus — não é falha, é o estado esperado
antes do bootstrap, e o cabeçalho do índice deve listar os submenus como pulados por
"grafia não declarada".

---

### F1 — Leitura de página inteira por rolagem

**Descrição.** Um reader genérico (`ScrolledAllFields`, no espírito de
`registry.AllFields`) que devolve os pares rótulo→valor de **toda** a página, não só
do screenful visível. Rola por `pagedown`/`pageup`, que movem um screenful por vez e
param nas pontas — confirmado ao vivo em 2026-08-24 sobre a página Main, que tem 73
linhas únicas contra ~31 visíveis de uma vez.

Reaproveita a mecânica já provada em `study_scroll_map.py`: normalizar ao topo antes
de mapear, assinatura estável (ignorando texto que muda sozinho, como relógio e
sensor), e detecção de fim por assinatura repetida.

**Detalhe carregador:** uma coordenada/posição só é válida na posição de rolagem em
que foi capturada. Toda estrutura que guarde posição guarda `screen_index` junto.

**Critérios de aceite**
- CA-F1.1 — Antes de mapear, o reader normaliza a posição enviando `pageup`
  `max_screens + 2` vezes, de modo que duas chamadas consecutivas na mesma página
  produzam o mesmo conjunto de linhas.
- CA-F1.2 — O fim da página é detectado por **assinatura de conteúdo repetida** entre
  screenful consecutivos, nunca por número fixo de rolagens; a busca para nesse ponto.
- CA-F1.3 — A assinatura ignora linhas cujo conteúdo é majoritariamente dígitos
  (`digitos * 2 >= len(texto)`), para que relógio/RPM não impeçam a terminação.
- CA-F1.4 — Linhas que aparecem em dois screenful consecutivos por sobreposição
  aparecem **uma única vez** no resultado agregado.
- CA-F1.5 — Só linhas do painel de conteúdo entram (`bbox.left >=
  navigate.SIDEBAR_MAX_X`); a barra lateral, que não rola, é excluída.
- CA-F1.6 — Cada linha mapeada carrega o `screen_index` em que foi vista; nenhuma
  entrada do resultado tem posição sem `screen_index`.
- CA-F1.7 — Existe um teto `max_screens` (padrão 12) e, ao atingi-lo sem detectar
  fim, o resultado é devolvido marcado como **truncado** em `notes` — nunca em
  silêncio nem em laço infinito.
- CA-F1.8 — Sobre uma página com 73 linhas únicas distribuídas em ≥3 screenful (via
  sessão fake nos testes), o reader devolve as 73 linhas; a leitura de uma única tela
  devolveria ≤31.
- CA-F1.9 — Todas as teclas usadas pertencem a `registry.SAFE_KEYS`.

---

### F2 — Alcance genérico a submenus

**Descrição.** Uma função de navegação que alcança uma tela **um nível abaixo** de uma
tela de topo (Hardware Monitor, Trusted Computing, Device Control, Network Stack,
MAPT, Smart Charging, TLS Auth, PAP — todas dentro de Advanced), sem uma tool escrita
para cada uma.

Fluxo: `navigate.enter_main_menu_screen` leva à tela de topo (mesma navegação ancorada
no ícone "Setup" já existente), depois o item de submenu é localizado **por
rótulo declarado** e ativado.

**Critérios de aceite**
- CA-F2.1 — Existe um mapa declarado `SUBMENUS: canonical_submenu -> canonical_parent`
  (ex.: `hardware_monitor -> advanced`), com provenance por entrada no mesmo padrão de
  `labels.py` (`"CONFIRMADO"` vs `"palpite"`). Só entradas presentes no mapa são
  navegáveis; um nome ausente do mapa nunca é tentado.
- CA-F2.1a — **Semântica exata de `provenance: "palpite"`**, por caminho, sem exceção:
  | Caminho | Entrada CONFIRMADO | Entrada `palpite` |
  |---|---|---|
  | F2 chamada diretamente (CLI/estudo, destino nomeado pelo operador) | navega | **navega**, e o resultado traz em `notes` "submenu não confirmado em hardware" |
  | F3 tour | visita | **não visita**; entra em `skipped` com motivo `"provenance=palpite"` |
  | F4 `find_setting` | navega | **não navega**; abstém-se como em CA-F4.6 |
  | Contagem do KPI K6 | conta | **não conta** |
  Nenhum outro caminho pode consumir `SUBMENUS`.
- CA-F2.2 — O item de submenu é encontrado por conteúdo, via
  `screen.match_score` contra `labels.screen(<submenu>)`, **nunca** por índice fixo na
  lista.
- CA-F2.3 — Pedir um submenu desconhecido devolve erro nomeando os conhecidos, sem
  navegar e sem casar com o mais parecido.
- CA-F2.4 — A chegada é **verificada** após o `enter`: a tela resultante contém uma
  grafia declarada do submenu (ou um rótulo declarado como pertencente a ele); se não
  contiver, o resultado é falha explícita, não sucesso otimista.
- CA-F2.5 — Se o item de submenu não está no screenful visível, a busca usa F1 para
  rolar a tela de topo até encontrá-lo antes de desistir.
- CA-F2.6 — Falha em chegar à tela de topo aborta antes de qualquer `enter`, com o
  motivo propagado de `enter_main_menu_screen`.
- CA-F2.7 — `save_and_exit` é rejeitada como pai ou como destino (R6).
- CA-F2.8 — Todas as teclas usadas pertencem a `registry.SAFE_KEYS`.
- CA-F2.9 — Chamar duas vezes em sequência na mesma sessão funciona: o submenu aberto
  é fechado (`esc`) quando o chamador pede restauração, como `Tool.run`/`_close_opened`
  já faz.

---

### F3 — Índice de rótulos da máquina

**Descrição.** Um estudo de bancada (`study_label_index.py`, na raiz, junto aos outros
estudos) que roda contra o hardware real, visita todas as telas de topo exceto
`save_and_exit`, desce em cada submenu declarado, rola cada página até o fim (F1), e
salva um artefato **versionado** `rótulo → onde ele está`.

É material colhido de hardware real, nunca inventado — mesma disciplina de
`biostools/labels.py`. O projeto já perdeu um corpus por não commitar
(`docs/specs/p-specs/fixture-de-teste-nunca-versionada.md`), e a demo inteira depende
deste índice.

**Critérios de aceite**
- CA-F3.1 — O índice é gravado em `data/label_index.json` (caminho fixo, dentro do
  repositório, **commitado**), e não em diretório temporário nem ignorado pelo git.
- CA-F3.2 — Cada entrada tem: `label` (texto como lido), `page` (id da página onde
  vive, ver CA-F3.2a), `screen_index` (posição de rolagem dentro daquela página),
  `value` (texto à direita, ou `null`), `provenance` (`"CONFIRMADO"` + modelo/data da
  captura).
- CA-F3.2a — O índice tem uma seção `pages`, uma entrada por página visitada, com
  `page_id`, `screen` (tela de topo canônica), `submenu` (canônico ou `null`),
  `total_screens` (quantos screenful a página tem) e `signatures`: a assinatura
  estável de **cada** `screen_index`, na forma que F1 calcula (CA-F1.3). Toda
  `LabelEntry.page` referencia um `page_id` existente.
  Isto existe porque P2 (reposicionamento) precisa de `total_screens` para saber
  quantos `pageup` enviar, e de `signatures[screen_index]` para **verificar** que
  chegou onde o índice diz — sem os dois no arquivo, F4 não consegue executar P2 a
  partir de uma entrada lida do disco.
- CA-F3.3 — Toda entrada do índice tem `provenance == "CONFIRMADO"`; o tour não grava
  entradas previstas/adivinhadas.
- CA-F3.4 — O índice carrega um cabeçalho com `bios_model`, `bios_version`
  (`2.22.0058` no alvo), `captured_at` e a lista de telas/submenus **visitados** e
  **pulados** com motivo.
- CA-F3.5 — `save_and_exit` não aparece no índice e é listada como pulada com motivo
  explícito (R6).
- CA-F3.6 — O tour envia exclusivamente teclas de `registry.SAFE_KEYS`; um teste
  estático sobre uma sessão fake que registra as teclas prova que nenhuma tecla de
  alteração (`+`, `-`, `f10`, `y`) foi enviada em nenhum momento.
- CA-F3.7 — O tour abre exatamente uma `BiosSession` e a reutiliza para todas as
  telas (R4).
- CA-F3.8 — A falha em uma tela (submenu inalcançável, leitura vazia) **não aborta o
  tour**: a tela entra no cabeçalho como pulada com motivo, e o resto é visitado.
- CA-F3.9 — O índice é carregável por um leitor puro (sem hardware), que valida o
  esquema e recusa um arquivo com: entrada sem `screen_index`, sem `provenance`, com
  `page` inexistente em `pages`, com `screen_index >= pages[page].total_screens`, ou
  com `pages[page].signatures` faltando algum índice de `0..total_screens-1`.

---

### F4 — `find_setting`: o caminho universal de resposta

**Descrição.** Uma tool (com `router`, como `goto_screen`) que recebe o termo da
pergunta, procura no índice de F3, navega até a tela (F2 quando é submenu), rola até o
`screen_index` certo (F1) e lê o valor ali. É o caminho que responde quando nenhuma
tool nomeada existe.

**Critérios de aceite**
- CA-F4.1 — A tool tem **dois** parâmetros: `term` (string, obrigatório — o nome do
  ajuste procurado) e `question` (string, opcional — a frase original do operador,
  repassada para diagnóstico e para a checagem de CA-F4.9). `term` ausente ⇒
  `ok=False` com erro nomeando o parâmetro faltante.
- CA-F4.1a — **Divisão de responsabilidade pela intenção**, para que CA-F4.9 e
  CA-F4.12 sejam implementáveis sem que alguém invente a arquitetura:
  - O **assistente** (`biostools/assistant.py`) é quem escolhe qual tool chamar e
    quem extrai `term` da pergunta. É lá que vive a precedência de CA-F4.12: se
    alguma tool nomeada declara cobrir a pergunta, ela é chamada; `find_setting` é o
    fallback, e a decisão é do modelo a partir das descrições das tools — nenhuma
    lista de dicas escrita à mão por tela (que é justamente o buraco 3 de
    `descriptions.md`).
  - `find_setting` **também** aplica a guarda de escrita de CA-F4.9 sobre `term` e
    `question` — guarda redundante de propósito: a fronteira somente-leitura não pode
    depender do julgamento do modelo. Redundância na barreira de segurança é
    deliberada, não duplicação a eliminar.
- CA-F4.2 — A busca no índice usa `screen.match_score` e prefere casamento
  normalizado exato sobre containment (mesma regra de `study_scroll_map.find_in_map`:
  `Main` é substring de `Domain`).
- CA-F4.3 — Termo **não encontrado no índice** ⇒ `ok=True`, `kind="field"`,
  `value=None`, e uma afirmação de conhecimento: *"esse ajuste não existe na BIOS
  desta máquina"*, acompanhada em `notes` de **onde procurou** (telas e submenus
  cobertos pelo índice, com data de captura). Esta resposta é distinta de falha.
- CA-F4.4 — Falha de navegação/leitura para um termo **que está** no índice ⇒
  `ok=False` com erro descrevendo a falha. As duas situações de CA-F4.3 e CA-F4.4
  nunca produzem a mesma mensagem.
- CA-F4.5 — Índice ausente ou inválido ⇒ `ok=False` com erro instruindo a rodar o
  tour de F3; nunca cai num caminho de adivinhação.
- CA-F4.6 — Empate ou casamento apenas fraco/ambíguo (mais de um candidato com o
  mesmo score) ⇒ **abstenção**, listando os candidatos, jamais escolha silenciosa de
  um deles (R2, R3).
- CA-F4.7 — Ao navegar, usa F2 quando a entrada tem `submenu`, e
  `enter_main_menu_screen` direto quando não tem; e rola exatamente até
  `screen_index` pelo procedimento de reposicionamento (topo, depois N `pagedown`).
- CA-F4.8 — Antes de ler, **verifica** que a tela atual é a esperada
  (`screen.screen_id` / grafia declarada); divergência ⇒ falha explícita, não leitura
  da tela errada (R5).
- CA-F4.9 — Quando `term` ou `question` contém um pedido de alteração ("desliga o
  Fast Boot", "muda o boot order", "ativa o TPM"), a tool recusa com mensagem de
  fronteira deliberada citando somente-leitura, **sem enviar nenhuma tecla** (R1). A
  detecção é por lista declarada de verbos de alteração (declarada, não adivinhada —
  R3); na dúvida a tool **não** recusa, apenas lê, porque ler é seguro e recusar uma
  pergunta legítima é o erro barato aqui.
- CA-F4.10 — O `ToolResult` devolvido preenche `screen_id`, `steps`, `label`, `row` e
  `abstentions` como as tools existentes, para não exigir um segundo formato de saída.
- CA-F4.11 — A tool é registrada em `registry` e exposta como subcomando de CLI
  (`__main__.py`) e como tool do assistente, como as demais.
- CA-F4.12 — `find_setting` só é acionada quando nenhuma tool nomeada cobre a
  pergunta; a existência de tool nomeada continua tendo precedência (camada de
  velocidade sobre a cobertura). Implementado como descrito em CA-F4.1a.

---

### F5 — Banco de perguntas (instrumento de medição dos KPIs)

**Descrição.** K1–K4 — incluindo **K1, o número mais importante do slug** — só são
mensuráveis contra um conjunto fixo e versionado de perguntas reais. Sem ele os KPIs
principais não existem, então o banco é entregável deste slug, não um pressuposto.

**Critérios de aceite**
- CA-F5.1 — Existe `specs/cobertura-universal-bios/question-bank.md`, versionado, com
  ≥ 40 perguntas.
- CA-F5.2 — Cada pergunta tem: `id`, `texto`, `origem` (`ensaiada` \| `nao-ensaiada`),
  `autor`, e `expectativa` ∈ {`valor:<esperado>`, `nao-existe`,
  `fora-de-escopo-escrita`}.
- CA-F5.3 — ≥ 10 perguntas são `nao-ensaiada`. **Entrada humana obrigatória:** são
  escritas por uma pessoa que não viu a implementação. O impl-loop **não pode
  gerá-las** — perguntas escritas por quem escreveu o código não medem o que K1 mede.
- CA-F5.4 — ≥ 5 perguntas têm expectativa `nao-existe` (para exercitar CA-F4.3) e
  ≥ 3 têm `fora-de-escopo-escrita` (para exercitar CA-F4.9).
- CA-F5.5 — Enquanto CA-F5.3 não estiver satisfeito, o runner de KPIs **falha com
  mensagem explícita** ("banco incompleto: N perguntas não ensaiadas, mínimo 10") em
  vez de reportar K1–K4 sobre um banco parcial. Um K1 = 0 medido sobre perguntas
  ensaiadas é enganoso, e enganoso é pior que ausente.
- CA-F5.6 — O runner de KPIs (`tests/kpis.md`) consome este arquivo e produz o
  relatório de três classes.

**Débito consciente:** F5 tem uma dependência humana bloqueante (CA-F5.3). O slug
pode ser implementado e ter F0–F4 aprovados sem ela; o que **não** pode é declarar
K1–K4 atingidos. Isso está registrado no gate abaixo.

**Gate de conclusão do slug:** F0–F4 completos e K5–K11 verdes ⇒ implementação
pronta. K1–K4 só são declaráveis depois de F5 completo com as perguntas não ensaiadas
escritas por humano e da execução de bancada.

---

## Procedures

### P1 — Ler uma página inteira (F1)

Entrada: `session`, `max_screens`. Saída: `[{index, signature, lines}]` + pares
agregados rótulo→valor + `notes`.

1. Enviar `pageup` × (`max_screens` + 2) para normalizar ao topo.
2. Para `index` em `0..max_screens-1`:
   1. `session.read_stable()` (aguardar a tela parar de mudar).
   2. Filtrar linhas do painel de conteúdo (`bbox.left >= SIDEBAR_MAX_X`).
   3. Calcular assinatura estável (descartando linhas majoritariamente numéricas).
   4. Se a assinatura for igual à do screenful anterior ⇒ fim da página, parar.
   5. Guardar `{index, signature, lines}` com bbox **desta** posição de rolagem.
   6. `session.press("pagedown")`.
3. Se o laço terminou por atingir `max_screens`, anexar nota de truncamento.
4. Agregar pares rótulo→valor deduplicando por rótulo normalizado, mantendo a
   primeira ocorrência e seu `screen_index`.

### P2 — Reposicionar em um `screen_index` (F1/F4)

Entrada: `session`, `page` (o registro de `LabelIndex.pages`, que traz
`total_screens` e `signatures` — ver CA-F3.2a), `screen_index`.
Saída: sucesso, ou falha nomeada `INDICE_DESATUALIZADO`.

1. `pageup` × (`page.total_screens` + 2) — normaliza ao topo.
2. `pagedown` × `screen_index`.
3. `session.read_stable()`; calcular a assinatura estável da tela atual (mesma regra
   de CA-F1.3).
4. Comparar com `page.signatures[screen_index]`. O critério é **sobreposição
   suficiente**, não igualdade exata: ≥ 70% das linhas da assinatura registrada
   presentes na atual. Igualdade exata falharia por um único glifo de OCR diferente
   entre capturas; 70% distingue "mesma tela, ruído de OCR" de "outra tela".
5. Abaixo do limiar ⇒ falhar com `INDICE_DESATUALIZADO`, dizendo qual `page_id` e
   `screen_index` divergiram e instruindo a re-rodar o tour de F3. Nunca ler assim
   mesmo (R5).

### P3 — Entrar em um submenu (F2)

Entrada: `session`, `submenu` canônico, `mode`. Saída: `NavigationResult`-like.

1. Resolver `parent = SUBMENUS[submenu]`; desconhecido ⇒ erro nomeando conhecidos.
2. Recusar se `parent` ou `submenu` for `save_and_exit`.
3. `navigate.enter_main_menu_screen(session, parent, mode=mode)`; falha ⇒ abortar.
4. Procurar o item por `match_score` contra `labels.screen(submenu)` no screenful
   atual; se não achar, rolar com P1 até achar ou até o fim da página.
5. Mover o cursor até o item (`navigate.move_to`) e ativar (`navigate.activate`).
6. Ler e **verificar** a chegada; divergência ⇒ falha com motivo.
7. Se o chamador pediu restauração, `esc` ao final para voltar à tela de topo.

### P3a — Colheita de grafias cruas (F0)

Precede P4 na primeira vez que uma máquina é mapeada.

1. Abrir **uma** `BiosSession`.
2. Para cada tela de `TOP_LEVEL_SCREENS` menos `save_and_exit`:
   1. `enter_main_menu_screen`; falha ⇒ registrar e seguir.
   2. Executar P1 e escrever **todo** texto do painel de conteúdo em
      `data/raw_labels/<screen>.json`, com `screen_index` e `bbox`. Sem casar contra
      `labels.py`, sem entrar em submenu.
3. **Passo humano, fora do software:** revisar os dumps, identificar quais linhas são
   entradas de submenu, e editar `biostools/labels.py` e `SUBMENUS` marcando
   `# CONFIRMADO -- Positivo, <data>` só no que foi visto. Nenhum código deste slug
   escreve nesses arquivos (CA-F0.3).

### P4 — Tour de índice (F3)

Pré-requisito: P3a concluído (incluindo o passo humano), senão os submenus caem em
`skipped` com motivo `"grafia não declarada"` — estado esperado, não falha.

1. Abrir **uma** `BiosSession`.
2. Para cada tela de `TOP_LEVEL_SCREENS` menos `save_and_exit`:
   1. `enter_main_menu_screen`; falha ⇒ registrar como pulada com motivo, seguir.
   2. Executar P1. Criar um `PageRecord` com `page_id`, `screen`, `submenu=null`,
      `total_screens` e `signatures` de cada `screen_index`. Registrar cada linha
      como `LabelEntry` apontando para esse `page_id`.
   3. Para cada `submenu` de `SUBMENUS` cujo pai é esta tela **e cuja provenance é
      CONFIRMADO** (CA-F2.1a): P3, depois P1, criando outro `PageRecord` com
      `submenu` preenchido e suas entradas; `esc` para voltar. Falha ⇒ pulada com
      motivo. Provenance `palpite` ⇒ pulada com motivo `"provenance=palpite"`.
3. Escrever `data/label_index.json` com cabeçalho (modelo, versão, `captured_at`,
   visitados, pulados+motivo), `pages` e `entries`.

### P5 — Responder uma pergunta genérica (F4)

Entrada: `term` (obrigatório), `question` (opcional). O assistente já decidiu que
nenhuma tool nomeada cobre esta pergunta (CA-F4.1a).

1. Se `term` ou `question` casa a lista declarada de verbos de alteração ⇒ recusar
   por fronteira somente-leitura, sem enviar tecla (CA-F4.9). Fim.
2. Carregar `data/label_index.json`; ausente/inválido ⇒ `ok=False` instruindo rodar
   P4. Nunca degradar para adivinhação.
3. Casar `term` contra os `label` do índice via `screen.match_score`, preferindo
   casamento normalizado exato sobre containment.
   - Nenhum candidato ⇒ afirmação "esse ajuste não existe na BIOS desta máquina" +
     escopo (telas/submenus de `visited` + `captured_at`). `ok=True`, `value=None`.
   - Empate de score entre candidatos distintos ⇒ abstenção listando-os. `ok=True`,
     `value=None`.
4. Resolver `page = pages[entry.page]`. Se `page.submenu` não é null: P3 (rejeitando
   provenance `palpite`, CA-F2.1a); senão `enter_main_menu_screen(page.screen)`.
5. Reposicionar por P2, passando `page` e `entry.screen_index`.
6. Verificar `screen.screen_id` contra o esperado; ler o valor à direita do rótulo
   (`screen.field_value`).
7. Devolver `ToolResult` completo (CA-F4.10).

---

## Data Models

### `PageScan` (F1, em memória)
| Campo | Tipo | Invariante |
|---|---|---|
| `screens` | list[`ScreenSlice`] | índices contíguos a partir de 0 |
| `truncated` | bool | True sse parou por `max_screens` |
| `notes` | list[str] | não vazio quando `truncated` |

### `ScreenSlice`
| Campo | Tipo | Invariante |
|---|---|---|
| `index` | int ≥ 0 | igual à posição na lista |
| `signature` | set[str] | difere da do slice anterior |
| `lines` | list[line] | bbox válido **apenas** neste `index` |

### `SubmenuMap` (F2, declarado em código)
| Campo | Tipo | Invariante |
|---|---|---|
| `submenu` | str canônico | existe em `labels.SCREENS` |
| `parent` | str canônico | pertence a `navigate.TOP_LEVEL_SCREENS`, ≠ `save_and_exit` |
| `provenance` | `"CONFIRMADO"` \| `"palpite"` | só CONFIRMADO é usado por F3/F4 |

### `LabelIndex` (F3, `data/label_index.json`, versionado)
Cabeçalho:
| Campo | Tipo | Invariante |
|---|---|---|
| `bios_model` | str | ex. `"Positivo"` |
| `bios_version` | str | ex. `"2.22.0058"` |
| `captured_at` | str ISO | presente |
| `visited` | list[{screen, submenu}] | não vazio |
| `skipped` | list[{screen, submenu, reason}] | contém `save_and_exit` com motivo |
| `pages` | list[`PageRecord`] | ≥ 1; `page_id` único |
| `entries` | list[`LabelEntry`] | ≥ 1 |

`PageRecord` — **o que torna P2 executável a partir do disco**:
| Campo | Tipo | Invariante |
|---|---|---|
| `page_id` | str | único no arquivo |
| `screen` | str canônico | ∈ visited |
| `submenu` | str canônico \| null | quando não-null, `SUBMENUS[submenu] == screen` |
| `total_screens` | int ≥ 1 | quantos screenful a página tem |
| `signatures` | dict[str(int) → list[str]] | chaves exatamente `0..total_screens-1` |

`LabelEntry`:
| Campo | Tipo | Invariante |
|---|---|---|
| `label` | str | não vazio |
| `page` | str | referencia um `PageRecord.page_id` existente |
| `screen_index` | int ≥ 0 | **obrigatório**, e `< pages[page].total_screens` — nunca posição sem índice de tela |
| `value` | str \| null | null quando a linha não é par rótulo/valor |
| `provenance` | `"CONFIRMADO"` | valor único permitido |

(`screen` e `submenu` de uma entrada são obtidos via `page` — guardados uma vez em
`PageRecord`, não repetidos por entrada, para que não possam divergir entre si.)

### `RawLabelDump` (F0, `data/raw_labels/<screen>.json`, versionado)
| Campo | Tipo | Invariante |
|---|---|---|
| `text` | str | texto cru, **sem** casamento contra `labels.py` |
| `screen` | str canônico | tela de topo onde foi visto |
| `screen_index` | int ≥ 0 | obrigatório |
| `bbox` | dict | válido apenas neste `screen_index` |

### `FindSettingOutcome` (F4)
Reusa `registry.ToolResult`. Discriminação obrigatória de três desfechos:
| Desfecho | `ok` | `value` | Sinal |
|---|---|---|---|
| Encontrado e lido | True | valor | `label`, `row`, `screen_id` preenchidos |
| Não existe nesta BIOS | True | None | nota "não existe na BIOS desta máquina" + escopo |
| Falha (navegar/ler/índice) | False | None | `error` descrevendo a falha |

---

## KPIs

Banco de perguntas: o artefato entregue por **F5**
(`specs/cobertura-universal-bios/question-bank.md`). K1–K4 são medidos sobre ele e
**não são declaráveis** enquanto CA-F5.3 (≥ 10 perguntas não ensaiadas, escritas por
humano) não estiver satisfeito — ver o gate de conclusão em F5.

| KPI | Feature relacionada | Meta | Como verificar |
|---|---|---|---|
| K1 — Taxa de resposta errada | F4 (e todo o slug) | **= 0** (zero absoluto) | Rodar o banco de perguntas contra a máquina; toda resposta com `ok=True` e `value` não-nulo é conferida contra o índice/tela. Ver `tests/kpis.md`. É o número mais importante. |
| K2 — Fração respondida corretamente | F1+F2+F3+F4 | ≥ 80% do banco de perguntas | Execução do banco; resposta correta = `value` confere com o que a tela mostra. `tests/kpis.md` |
| K3 — Qualidade da abstenção | F4 | **100%** das abstenções trazem em `notes` o escopo da busca (telas/submenus cobertos + `captured_at` do índice) e usam a formulação de inexistência, distinta de erro | Inspeção automática do `notes` de cada resposta com `value=None` no relatório do runner. Falha independentemente de K1/K2: uma abstenção sem escopo é um "não achei" ambíguo, exatamente o que `descriptions.md` proíbe. `tests/kpis.md` |
| K4 — Tempo até a resposta (demo ao vivo) | F4 | p95 ≤ 30 s por pergunta; **nenhuma** > 60 s | Cronometrar `find_setting` ponta a ponta no banco de perguntas. `tests/kpis.md` |
| K5 — Cobertura de rótulos da página Main | F1 | ≥ 73 linhas únicas mapeadas (contra ≤ 31 de uma leitura única) | `tests/f1-leitura-pagina-inteira.md` com sessão fake de 3+ screenful; e uma medição de bancada contra o hardware. |
| K6 — Submenus alcançáveis genericamente | F2 | ≥ 8 dos submenus declarados de Advanced alcançados e verificados na bancada | `tests/f2-submenus.md` + relatório do tour de F3 (`visited`). |
| K7 — Teclas fora de `SAFE_KEYS` emitidas | R1, F1, F2, F3, F4 | **= 0** | Teste com sessão fake que registra toda tecla; asserção de subconjunto de `SAFE_KEYS`. `tests/r1-somente-leitura.md` |
| K8 — Visitas a `save_and_exit` | R6, F3 | **= 0** | Log de navegação do tour e dos testes; asserção. `tests/f3-indice.md` |
| K9 — Entradas do índice sem `screen_index` ou sem `provenance` | F3 | **= 0** | Validador de esquema do índice, rodando sobre o `data/label_index.json` commitado. `tests/f3-indice.md` |
| K10 — Índice versionado presente | F3 | `data/label_index.json` rastreado pelo git e não vazio | `git ls-files data/label_index.json` no CI + checagem de ≥1 entrada. `tests/f3-indice.md` |
| K11 — Sessões abertas por execução do tour | R4, F3 | = 1 | Contador de instanciações de `BiosSession` na sessão fake. `tests/f3-indice.md` |
| K12 — Grafias CONFIRMADO sem evidência crua | F0, R3 | **= 0** | Para cada submenu `CONFIRMADO` em `SUBMENUS`, existe linha casável em `data/raw_labels/`. `tests/f0-bootstrap.md` (CA-F0.5) |
| K13 — Submenus alvo com grafia declarada | F0 | 8 de 8 | `labels.SCREENS` tem entrada para os oito submenus de `descriptions.md`. `tests/f0-bootstrap.md` |
| K14 — Completude do banco de perguntas | F5 | ≥ 40 perguntas, ≥ 10 não ensaiadas, ≥ 5 `nao-existe`, ≥ 3 `fora-de-escopo-escrita` | Validador de formato sobre `question-bank.md`, roda sem hardware. `tests/kpis.md` |

Feature sem KPI próprio: nenhuma. As restrições R2/R3/R5 não têm métrica numérica
isolada — R2/R5 são cobertas por K1 (zero resposta errada) e K3 (qualidade da
abstenção); R3 é coberta por K12. Não há métrica separada de "abstenção correta em
contagem" porque ela seria uma identidade aritmética de K1 e K2, e não poderia
reprovar nada sozinha.

---

## Fora de escopo

- Alterar qualquer ajuste da BIOS (permanece bloqueado por `SAFE_KEYS`).
- Visitar ou operar a tela `save_and_exit`.
- Tools nomeadas adicionais (`system_identity`, `security_status`, `boot_config`,
  `thermal_status`, `tpm_status`) e a tool composta `check_config`. Outro slug: este
  é a **cobertura**, aquele é a **camada rápida** em cima dela.
- Suportar um quarto modelo de BIOS. Alvo: Positivo, BIOS 2.22.0058.
- Navegação por mouse/clique como caminho principal (`study_scroll_map.py` a explora;
  aqui ela permanece apenas como fallback já existente de `enter_main_menu_screen`).
- Submenus com mais de um nível de profundidade (neto de tela de topo).
