# Testes — F4: `find_setting`

Sessão fake + um índice fixture em memória (não o índice real), para que os casos
sejam determinísticos.

## Caminho feliz

### CT-F4.1 — Termo na tela de topo
- **Dado** um índice com `pages: [{page_id: "p1", screen: "main", submenu: null,
  total_screens: 1, signatures: {...}}]` e
  `{label: "BIOS Version", page: "p1", screen_index: 0, value: "2.22.0058"}`
- **Quando** `find_setting(term="BIOS Version")` roda
- **Então** `ok=True`, `value="2.22.0058"`, `screen_id` preenchido
- **E** a navegação foi `enter_main_menu_screen("main")`, sem F2

### CT-F4.2 — Termo em submenu, abaixo da dobra
- **Dado** `pages: [{page_id: "p2", screen: "advanced", submenu: "hardware_monitor",
  total_screens: 4, signatures: {0:.., 1:.., 2:.., 3:..}}]` e
  `{label: "CPU Temperature", page: "p2", screen_index: 2}`
- **Quando** `find_setting(term="temperatura da CPU")` roda com a grafia declarada
  casando
- **Então** F2 foi usada para entrar em `hardware_monitor`
- **E** houve reposicionamento: exatamente `4 + 2 = 6` `pageup` (de
  `page.total_screens`), depois exatamente 2 `pagedown`
- **E** `ok=True` com o valor lido

### CT-F4.2a — `total_screens` vem do índice, não de um chute
- **Dado** duas páginas com `total_screens` 3 e 9
- **Quando** `find_setting` resolve um termo de cada
- **Então** a contagem de `pageup` difere (5 e 11), derivada do `PageRecord`

### CT-F4.3 — Preferência por casamento exato sobre containment
- **Dado** um índice com `"Main"` e `"Domain Name"`
- **Quando** `find_setting(term="Main")` roda
- **Então** a entrada escolhida é `"Main"`

### CT-F4.4 — `ToolResult` completo
- **Dado** qualquer resposta bem-sucedida
- **Então** `tool`, `ok`, `kind`, `value`, `label`, `row`, `screen_id`, `steps`,
  `notes`, `abstentions` estão presentes em `as_dict()`
- **E** `as_text()` produz uma linha legível

## Não encontrado vs. falha — a distinção que importa

### CT-F4.5 — Ajuste que não existe nesta BIOS
- **Dado** um índice válido sem nenhum casamento para `"Secure Boot Custom Mode"`
- **Quando** `find_setting(term="Secure Boot Custom Mode")` roda
- **Então** `ok=True`, `value=None`
- **E** a mensagem afirma que **o ajuste não existe na BIOS desta máquina**
- **E** `notes` lista **onde procurou**: telas e submenus cobertos e `captured_at` do
  índice
- **E** nenhuma tecla foi enviada (a resposta veio do índice)

### CT-F4.6 — Falha de navegação para termo que ESTÁ no índice
- **Dado** um termo presente no índice, mas `enter_main_menu_screen` falhando
- **Quando** `find_setting` roda
- **Então** `ok=False` com erro descrevendo a falha de navegação

### CT-F4.7 — As duas mensagens são distintas
- **Dado** os resultados de CT-F4.5 e CT-F4.6
- **Então** as mensagens ao operador diferem e nenhuma contém um "não achei"
  ambíguo que sirva para as duas

### CT-F4.8 — Índice ausente
- **Dado** que o índice não existe
- **Quando** `find_setting(term="qualquer")` roda
- **Então** `ok=False`, erro instruindo rodar o tour de F3
- **E** nenhuma navegação foi tentada
- (Nunca degrada para adivinhação.)

### CT-F4.9 — Índice com esquema inválido
- **Dado** um índice sem `provenance` nas entradas
- **Quando** `find_setting` roda
- **Então** `ok=False` com erro de esquema, não um resultado parcial

## Abstenção

### CT-F4.10 — Empate de candidatos
- **Dado** duas entradas do índice com o mesmo score contra o termo (ex.: `"CPU Fan
  Speed"` em duas telas)
- **Quando** `find_setting` roda
- **Então** `value=None` e a resposta lista os candidatos
- **E** nenhuma das duas foi escolhida silenciosamente

### CT-F4.11 — Nunca casar com a linha mais parecida
- **Dado** um índice com `"System Temperature"` e o termo `"CPU Temperature"`, sem
  entrada para o segundo
- **Quando** `find_setting` roda
- **Então** a resposta é a de CT-F4.5 (não existe nesta máquina)
- **E** `"System Temperature"` **não** é devolvida como resposta
- (O erro silencioso exato que `labels.py` existe para prevenir.)

### CT-F4.12 — Verificação de tela antes de ler
- **Dado** que a navegação reportou sucesso mas a tela alcançada tem `screen_id`
  diferente do esperado
- **Quando** `find_setting` roda
- **Então** `ok=False` com erro de verificação
- **E** nenhum valor da tela errada é devolvido

### CT-F4.13 — Reposicionamento cuja assinatura não bate
- **Dado** um `screen_index` cuja `pages[page].signatures[screen_index]` tem < 70% de
  sobreposição com a assinatura da tela atual (índice envelhecido)
- **Quando** `find_setting` roda
- **Então** `ok=False` com erro nomeado `INDICE_DESATUALIZADO`, citando `page_id` e
  `screen_index`, instruindo a re-rodar o tour
- **E** nenhum valor da tela é devolvido

### CT-F4.13a — Ruído de OCR não dispara falso `INDICE_DESATUALIZADO`
- **Dado** uma assinatura atual igual à registrada exceto por 2 linhas de 20
  corrompidas por OCR (90% de sobreposição)
- **Quando** `find_setting` roda
- **Então** a verificação passa e a leitura prossegue
- (Igualdade exata reprovaria; o limiar de 70% é o que distingue ruído de tela errada.)

## Somente leitura

### CT-F4.14 — Pedido de alteração é recusado
- **Dado** `find_setting(term="Fast Boot", question="desliga o Fast Boot")`
- **Quando** a tool roda
- **Então** o resultado é recusa explícita citando a fronteira somente-leitura
- **E** `session.pressed` está vazio
- (A guarda está **na tool**, não só no assistente: a fronteira somente-leitura não
  pode depender do julgamento do modelo — CA-F4.1a.)

### CT-F4.14a — Verbo de alteração no próprio `term`
- **Dado** `find_setting(term="ativar TPM")` sem `question`
- **Então** a recusa acontece igualmente

### CT-F4.14b — Pergunta de leitura não é recusada por engano
- **Dado** `find_setting(term="Fast Boot", question="o Fast Boot está ligado?")`
- **Então** a tool **não** recusa: ela procura e lê
- (CA-F4.9: na dúvida, ler — recusar pergunta legítima é o erro caro numa demo.)

### CT-F4.14c — `question` é opcional
- **Dado** `find_setting(term="BIOS Version")` sem `question`
- **Então** funciona normalmente

### CT-F4.15 — Somente `SAFE_KEYS`
- **Dado** todos os casos acima
- **Então** `set(session.pressed) ⊆ registry.SAFE_KEYS`

### CT-F4.16 — Rota declarada é segura na importação
- **Dado** o módulo da tool importado
- **Então** nenhum `UnsafeRoute` é levantado
- **E** a tool está registrada e aparece em `registry.all_tools()`

## Integração

### CT-F4.17 — Precedência de tool nomeada (no assistente)
- **Dado** a pergunta "qual a temperatura da CPU", coberta por `cpu_temperature`
- **Quando** o roteamento de `assistant.py` decide, com um cliente de modelo fake
- **Então** `cpu_temperature` é escolhida, não `find_setting`
- **E** o schema exposto ao modelo inclui `find_setting` com `term` e `question`
- (A decisão vive no assistente — CA-F4.1a — e é o que este caso verifica.)

### CT-F4.17a — Sem tool nomeada, cai em `find_setting`
- **Dado** a pergunta "qual o estado do Network Stack", sem tool nomeada
- **Então** o assistente chama `find_setting` com `term` extraído da pergunta

### CT-F4.17b — Sem dicas por tela escritas à mão
- **Dado** a descrição de `find_setting` exposta ao modelo
- **Então** ela **não** contém uma lista de mapeamentos tela↔assunto ("Fast Boot fica
  em boot, senhas em security")
- (É o buraco 3 de `descriptions.md`: o índice substitui o palpite.)

### CT-F4.18 — CLI
- **Dado** `py -3.13 -m biostools find-setting --term "BIOS Version"` (sem hardware,
  com sessão fake injetada)
- **Então** a saída estruturada é produzida no mesmo formato das demais tools
- **E** `--question` é aceito como flag opcional

### CT-F4.19 `[BANCADA]` — Pergunta não ensaiada
- **Dado** a máquina alvo e uma pergunta do banco marcada como não ensaiada
- **Quando** `find_setting` roda
- **Então** a resposta é correta ou é abstenção honesta — nunca errada
