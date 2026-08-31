# Camada de tools de consulta à BIOS (`biostools/`)

## Objetivo

Responder perguntas sobre a tela da BIOS por **tools nomeadas**: cada tool sabe navegar até a tela onde a resposta está, lê a resposta pelo motor de percepção, e devolve isso estruturado.

Existe porque o ciclo ler→agir→verificar foi provado em hardware real em 2026-08-20 (cabo USB-KM232 movendo o cursor, captura HDMI confirmando pelo OCR), mas o protótipo que provou isso — `bios_navigate_demo.py` — respondia **uma pergunta hardcoded** e rodava sobre o caminho legado (`selection.py`), não sobre o motor de percepção. Esta feature transforma aquilo num mecanismo: adicionar a próxima pergunta é preencher um `Tool(...)`, não escrever outro programa.

## Escopo

Começou com três tools definidas pelo usuário (`main_menu`, `main_info`, `cpu_temperature`); cresceu para **32** ao longo do projeto, a maioria em uma sessão só (2026-08-31) puxando o índice de rótulos e navegação ao vivo. Duas famílias de tool convivem:

- **Genéricas** (4): `goto_screen` (qualquer tela de topo, lê tudo), `find_setting`/`explore_setting` (qualquer ajuste pelo nome, índice ou varredura ao vivo), `main_menu` (caminha o menu).
- **Nomeadas** (28): uma pergunta fixa cada, agrupadas por onde vivem:

| Tela | Tools |
|---|---|
| Main | `main_info`, `bios_info`, `system_datetime`, `ec_info`, `product_info`, `memory_info`, `mac_address`, `management_engine_info` |
| Security | `password_policy`, `flash_protection_status`, `removable_storage_policy` |
| Boot | `fast_boot_status`, `numlock_settings`, `bios_post_settings`, `boot_hotkeys`, `boot_order`, `boot_device_integrity` |
| Advanced (campos próprios) | `wake_settings`, `usb_charger_mode`, `sata_mode`, `graphics_settings`, `virtualization_status`, `audio_dsp_status` |
| Advanced → Hardware Monitor | `cpu_temperature`, `fan_speed` |
| Advanced → Trusted Computing | `tpm_status` |
| Advanced → Device Control | `device_control_info` |
| Advanced → Absolute Persistence(R) Module | `absolute_persistence_status` |

A lista completa e atualizada, sempre: `py -3.13 -m biostools --list`.

- **Dentro**: sessão compartilhada (câmera + pipeline quente + atuador), leitura do contrato com resolução de cursor, navegação verificada com guardas de parada, caminhada por menu, extração de pares rótulo→valor (com rolagem de página quando o campo mora além do primeiro screenful — ver "Rolagem de página" abaixo), registro declarativo, CLI, e suíte offline (`test_biostools.py`).
- **Fora**: alterar configuração da BIOS — esta geração **observa**, e `registry.SAFE_KEYS` recusa rota que use tecla capaz de modificar (`+`/`-`/F10/`y`). Também fora: tool-calling por LLM (a saída já nasce estruturada para isso, mas nada foi ligado a um modelo) e empacotamento em `.exe`.
- **Não substitui** `bios_navigate_demo.py`, que fica como registro do experimento.

## Comportamento esperado

```
py -3.13 -m biostools --list
py -3.13 -m biostools main-menu --serial-port COM3 --text
py -3.13 -m biostools cpu-temperature --serial-port COM3
```

Como biblioteca — a forma que importa para uma tool chamar outra:

```python
from biostools import BiosSession, run_tool

with BiosSession(camera_source=0, serial_port="COM3") as session:
    print(run_tool("cpu_temperature", session).as_text())
```

Saída JSON por padrão (o consumidor de hoje pode ser um script ou outra tool), `--text` para operador, código de saída 1 quando não houve resposta. O JSON traz sempre as três chaves de payload (`value`, `values`, `entries`) mais `kind` dizendo qual delas carrega a resposta, para o consumidor não precisar ramificar antes de ler.

**Fluxo**: para cada perna da rota, mover o cursor até a entrada alvo relendo a tela a cada tecla; no fim, o *reader* da tool extrai a resposta. Nunca se assume que a tecla chegou: o cabo confirma entrega (ACK por byte), mas entrega não é a BIOS ter movido o destaque — a tela é a única autoridade sobre onde o cursor está.

**Casos de borda**: abstenção do motor é resposta legítima ("não consegui determinar"), não erro — propagada em `abstentions`. Valor que não casa com o padrão esperado vira texto cru em vez de falha: uma leitura fora do formato é exatamente a anomalia que o sistema existe para expor. Falha de hardware (`CableNotResponding`, `CameraUnavailable`, cabo ausente) propaga como erro de setup, distinta de "a BIOS disse algo que não consegui ler".

## Detalhes técnicos

### `focused` não é `selected`

`perception/stages/e7_state.py:86-89` emite dois nomes de estado distintos:

| Canal | Nome | Significado |
|---|---|---|
| `S1_background`, `S2_chroma`, `S3_polarity` | `selected` | aba/página ativa |
| `S6_border` | `focused` | **cursor do teclado** |

`S6_border` é novo (commit `04d8015`) e fecha o teto de [`campo-focado-por-borda-sem-canal-no-e7.md`](../p-specs/campo-focado-por-borda-sem-canal-no-e7.md).

Consequência medida em `captures/positivo_advanced_hardware-monitor.jpg`: `cognition.fact_summary()` filtra `state["name"] != "selected"` (`cognition.py:39`) e por isso reporta apenas `[g001] SELECTED: 'Advanced'` + `[g003] UNDETERMINED` — **não reporta nada** sobre `Hardware Monitor` estar `focused` com confiança 0.88 em `g002`. Navegação construída sobre `fact_summary` seria cega justamente para a linha onde o cursor está. Por isso `screen.group_views` resolve os dois nomes e faz o lift abstenção-E7 → grupo por conta própria.

### Por que caminhar pelo menu, se uma leitura já lista tudo

Medido no mesmo fixture: o grupo `nav_menu` contém **oito** elementos — as seis opções reais (`Main`, `Advanced`, `Security`, `Boot`, `Save & Exit`, `Event Log`) **mais `POSITIVO` e `Setup`**, que são o logo. Eles caem na mesma coluna e o E5 os agrupa junto.

O cursor nunca pousa no logo. Caminhar é, portanto, o que separa opção de decoração — e de quebra prova que cada opção é alcançável. É esse o ganho que justifica gastar uma leitura por entrada.

**A caminhada percorre as duas direções.** Um menu que dá a volta é coberto por uma passada só, mas um que para nas pontas não: começando no meio, uma passada única para baixo reportaria silenciosamente só a metade de baixo. A passada reversa só roda depois de um *stall* (cursor parou de andar); depois de uma volta completa ela seria puro retrabalho. As duas condições de parada são distintas de propósito — ver `CYCLE`/`STALL` em `navigate.py`.

Duas correções que a suíte offline pegou e que não são óbvias:
- a passada reversa começa em terreno que a passada de ida já cobriu, então parar na primeira entrada "já vista" a encerrava antes de ela sair do lugar. A parada correta é voltar à entrada **inicial daquela passada**, não a qualquer entrada já vista.
- um cursor que não anda produzia uma caminhada de **uma** entrada, que se passava pela lista inteira. `WalkResult.moved` distingue isso: sem movimento, a tool devolve a lista da leitura única marcada como **não confirmada**, em vez de mentir.

A lista é reportada em **ordem de tela**, não de visita: um menu que dá a volta é entrado onde quer que o cursor estivesse, e a sequência de visita fica rotacionada em relação ao que a pessoa vê.

### Leitura de valores

**Valor se lê à direita do rótulo, não pela linha inteira.** Medido em `captures/positivo_advanced_cpu-overheat.jpg`: o logo `Setup` (x=645) cai a 14px do centro vertical da linha de `CPU Temperature` (x=1471), então juntar a linha toda produz `'Setup CPU Temperature 61C'`. `screen.field_value` só considera primitivas com `x >= borda_direita_do_rótulo`. Apertar a tolerância vertical até `Setup` sair começaria a perder valores legítimos; a restrição horizontal resolve sem esse custo.

**Para "o que esta tela informa" (`AllFields`), dois filtros são necessários**, e a medição fixa o segundo:

| Par | Distância rótulo→valor | % da largura (3840) |
|---|---|---|
| `CPU Temperature` → `61C` | 592 | 15% |
| `CPU Fan Speed` → `3098 RPM` | 640 | 17% |
| `» CPU SMART FAN Configuration` → `Previous` (ruído) | 1287 | **34%** |

`Previous` é a caixa de ajuda da borda direita, que compartilha linha com o conteúdo por coincidência de layout, não de significado. `MAX_PAIR_GAP_RATIO = 0.25` separa os dois casos com margem dos dois lados. O outro filtro exclui os elementos do `nav_menu`, que também são "texto mais à esquerda da linha" e virariam rótulos.

**Parear por linha exige olhar região, não só distância.** Validado contra a tela Main real (`captures/positivo_main_live.png`, capturada ao vivo pela HDMI a 1280x720), onde a barra lateral fica a apenas **216-261px** da coluna de conteúdo — dentro de qualquer limite de distância razoável, então distância não separa. As regiões do próprio motor separam: rótulos e valores dividem o painel `r002`, enquanto a barra lateral e a caixa de ajuda caem fora dele.

Sem esse filtro, `'Advanced'` era reportado como rótulo com valor `'BIOS Version'` — e isso **engolia a linha do `BIOS Version` de verdade**, ou seja, a resposta que a tool existe para dar sumia, em vez de apenas ganhar um vizinho ruim. Falha silenciosa, não barulhenta.

**Linhas são agrupadas dentro de cada região, não pela tela toda.** "Mesma linha" só significa "mesmo campo" dentro de um painel: na tela Main o ritmo da barra lateral (26px) difere do conteúdo (36px), e intercalar os dois deixava uma entrada lateral capturar um valor de conteúdo antes do rótulo dele chegar. Duas medidas concretas dessa falha, ambas cobertas por teste agora:
- a âncora vertical da linha ficava no primeiro item a chegar. `'Event Log'` (31px de altura, centro 291.5) abria a linha e absorvia o valor `'01.22'` (centro 302.5), enquanto o rótulo dele, `'EC FW Version'` (centro 304.0), caía fora da tolerância que encolhia — e esse campo sumia. A âncora agora é a média corrente dos membros.
- tomar o item mais à esquerda como rótulo descartava a linha inteira quando esse item era da barra lateral. Foi assim que `System Time`, `BIOS Version` e outros dois se perderam.

`main_info` usa `AllFields` em vez de uma lista fixa de rótulos porque os rótulos variam entre modelos de BIOS, e os três modelos que a fábrica precisa atender podem escrevê-los diferente. Uma lista fixa devolveria silenciosamente menos quando um rótulo não casasse. Na tela Main real isso rende **11 campos** sem que nenhum precisasse ser nomeado, incluindo `BIOS Version -> 7.2.4.XD22CPG7.I219V.P`.

### Cursor pelo caminho legado, não pelo E7

**A navegação lê o cursor por `selection.py`, não pelos canais do motor de percepção.** Medido na mesma tela real, capturada por HDMI:

| Caminho | Vê o cursor? | Tempo |
|---|---|---|
| percepção + `rapidocr-openvino` (default) | **não** | 0.60s |
| percepção + `paddleocr` | sim | 13s |
| **`selection.py` + `rapidocr-openvino`** | **sim** | **0.66s** |

A causa está aberta em [`caixa-de-deteccao-engloba-barra-de-destaque.md`](../p-specs/caixa-de-deteccao-engloba-barra-de-destaque.md): o `S1_background` do E7 amostra o fundo no perímetro da caixa de OCR, e a caixa ultrapassa a barra de destaque em 2-3px (barra y=134..151, caixa y=134..153), então o anel cai no painel escuro e **todos os elementos medem o mesmo fundo** — desvio 0.00 na classe inteira. `selection.py` mede cor de outro jeito e não é afetado.

Isto **não** é um motor novo competindo com `perception/`: manter os dois caminhos é a decisão registrada do projeto ([`motor-percepcao-interface.md`](motor-percepcao-interface.md), "Coexistência"), e `gui.py` já escolhe entre eles com `--legacy`. A leitura de campo continua indo pelo contrato, onde foi validada. O efeito prático foi **63.5s → ~5s** sem trocar de motor de OCR.

### Repetibilidade e navegação desnecessária

Duas correções que só apareceram rodando ao vivo:

- **`Tool.restore`** (default ligado) dá um ESC por ENTER que a tool deu, inclusive nos caminhos de falha. Sem isso a tool era de uso único: a primeira execução deixava a BIOS *dentro* do Hardware Monitor, onde essa entrada não existe mais na lista, e a seguinte falhava com `not_found_after_full_cycle`.
- **`Fields.identifies_screen`** faz a tool responder sem mover nada quando a resposta já está na tela. Um rótulo nomeado identifica sua própria página (`CPU Temperature` só existe na do Hardware Monitor), então achá-lo é prova de estar no lugar certo. `AllFields` declara o contrário de propósito: qualquer página tem pares rótulo→valor, então lê-los não prova *qual* página é.

### Guardas de segurança

- *Detecção de ciclo*: se o cursor volta a uma entrada já visitada, a lista deu a volta (ou travou numa ponta) sem o alvo aparecer → para. Contra um alvo inexistente, para depois de **1 tecla** em vez do teto cego de 20 que o protótipo tinha.
- *Cursor indeterminado → zero teclas*: `navigate.py` relê até `blind_retries` vezes mas **nunca aperta às cegas**, porque o motor dá respostas diferentes para capturas diferentes da mesma tela — uma abstenção isolada vale reler, nunca vale apertar sem saber onde o cursor está.

### Custo de partida, medido

Medido ao vivo em 2026-08-20 contra a capture card HDMI a 1280x720:

| Fase | Custo |
|---|---|
| `import biostools` | 0.95s |
| abrir câmera + warmup (8 quadros) | 1.01s |
| carregar modelo de OCR (uma vez) | 0.02s |
| 1ª leitura (percepção completa) | 2.45s |
| leituras seguintes | **0.58s** |

Pronto para responder em ~2s. Antes de 2026-08-20 a abertura da câmera sozinha custava **25-28s** — ver [`abertura-de-camera-lenta-no-backend-padrao.md`](../p-specs/abertura-de-camera-lenta-no-backend-padrao.md); `BiosSession` usa `capture.open_camera`, não `cv2.VideoCapture`, por causa disso.

As leituras também saem bem abaixo dos 4.53s documentados em [`../d-specs/rapidocr.md`](../d-specs/rapidocr.md), medidos sobre fotos 4K de câmera. Um quadro HDMI 1280x720 é digital e limpo, e o OCR custa proporcionalmente menos.

### Pipeline quente

`perception.perceive()` reconstrói `Extraction` a cada chamada, recarregando o modelo de OCR (`perception/__init__.py:110`) — aceitável num tiro só, não num loop que lê a tela a cada tecla. `BiosSession` monta os dez estágios pós-aquisição uma vez e prefixa um `Acquisition` novo por leitura, mesmo padrão de `watcher.py:69-92`. Na mesma linha: `Tool.run` **pula** a leitura inicial quando a tool tem rota, porque `move_to` já lê primeiro — uma passada de OCR economizada por chamada.

Compartilhar a sessão é o que torna "tool chamando tool" viável. `import biostools` custa ~0.9s porque listar tools não pode carregar OCR — definições e motor são importados sob demanda.

Motor de OCR: o default do projeto ([`selecao-motor-ocr.md`](selecao-motor-ocr.md)). Cabo: [`cabo-usb-km232.md`](../d-specs/cabo-usb-km232.md).

### Rolagem de página

Um campo pedido nem sempre está no primeiro screenful da tela onde a tool navega — `registry.Fields`/`AllFields` aceitam `scroll=True` para continuar pressionando `scroll_key` até achar. O critério de quando parar de rolar (achou tudo, ou a página realmente acabou) foi corrigido duas vezes ao vivo em 2026-08-31, contra hardware real, depois de o primeiro critério (e o segundo) terem se mostrado errados em produção — ver [`sinal-de-progresso-de-rolagem-precisa-ser-a-pagina-inteira.md`](../p-specs/sinal-de-progresso-de-rolagem-precisa-ser-a-pagina-inteira.md) para a história completa e as medições. Resumo: o sinal de "ainda tem coisa nova" tem que ser o **texto bruto da tela inteira**, não o campo específico pedido nem só os pares rótulo→valor — os dois sinais mais estreitos liam prosa de ajuda rolando como "parei" e desistiam no meio de uma página que ainda tinha o campo pedido mais adiante.

## Critérios de aceite

`py -3.13 test_biostools.py` — suíte offline, sem câmera e sem cabo, com um `FakeBios` servindo contratos reais e movendo um cursor simulado. 28 verificações, cobrindo:

- os três estados (focado / selecionado / indeterminado) coexistindo numa tela só;
- leitura de campo rotulado e pares rótulo→valor com o ruído da caixa de ajuda filtrado;
- `main_info` contra a tela Main real: 11 campos, `BIOS Version` e `EC FW Version` corretos, barra lateral fora dos rótulos e caixa de ajuda fora dos valores;
- `cpu_temperature` fim a fim encadeando duas fixtures reais → `61C`, sem gastar seta (o cursor já estava no alvo);
- caminhada de menu nas duas topologias (dá a volta / para nas pontas), com o logo excluído e reportado como não-opção;
- cursor travado → responde mesmo assim, marcando a lista como não confirmada;
- as duas guardas de segurança.

As três fixtures são propositalmente de dois tipos de entrada: duas fotos 4K de monitor e uma captura HDMI 1280x720. Bordas duras e bordas suaves estressam a geometria de formas diferentes, e o teto de [`caixa-de-deteccao-engloba-barra-de-destaque.md`](../p-specs/caixa-de-deteccao-engloba-barra-de-destaque.md) é justamente sobre isso.

Os contratos são gerados uma vez das fixtures e cacheados em `.biostools_cache/` (ignorado pelo git), porque cada um custa uma passada de OCR.

Complementarmente: `py -3.13 -m perception.run --describe` continua listando os 11 estágios (nada do motor foi tocado).

## Status

**32 tools registradas — 2026-08-31.** Cresceu de 3 (2026-08-20) para 32 em várias sessões, a maior parte delas puxando conceitos já `CONFIRMADO` de `data/label_index.json` (o índice colhido em 2026-08-28) ou navegando ao vivo para os submenus de Advanced que aquele índice não cobria (Trusted Computing, Device Control, Absolute Persistence — este último nem estava previsto em `labels.py` até ser encontrado ao vivo). Suíte offline com mais de 100 verificações, `py -3.13 test_biostools.py` — "tudo passou".

**`cpu_temperature` validada fim a fim contra hardware real em 2026-08-20 — primeira tool a fechar o ciclo.** Partindo da página Advanced, navegou três passos sozinha (`MAC Address Pass-Through` → `Trusted Computing` → `Device Control` → `Hardware Monitor`), abriu com ENTER e leu `CPU Temperature: 64 C`. Conferido contra a tela: `64 C` e `3098 RPM` são o que o monitor mostrava. Roda com o motor default em ~5-10s e é repetível.

**27 das 28 tools nomeadas validadas ao vivo em 2026-08-31**, contra uma unidade real (Positivo, BIOS `1.2.5.XD22.I219V.P`) — incluindo todas as que dependem de rolagem de página, só depois da correção descrita em "Rolagem de página" acima. Só `main_menu`/`main_info` continuam bloqueadas (ver abaixo). A sessão de validação foi interrompida por uma falha de hardware real (o cabo USB-KM232 parou de responder, `CableNotResponding`) no meio de uma varredura completa — não uma falha de software; a maioria das tools já tinha sido confirmada individualmente antes disso.

## Questões em aberto

- **A barra lateral é indetectável enquanto o cursor está nela — é isto que bloqueia `main_menu` e `main_info`.** A semântica de foco foi medida tecla a tecla e não é mais incógnita: `left` leva do conteúdo para a lateral, **`right` volta**, `right` a partir do conteúdo vai para a coluna de ícones da direita, e `esc` sobe um nível. A lateral responde a up/down. O problema é outro: **a aba ativa e o cursor desenham barras escuras quase idênticas**, então com o cursor em `Main` e a aba em `Advanced` existem **duas barras**, e `selection.py` corretamente se recusa a eleger uma (devolve vazio, pela própria disciplina de "um único vencedor"). Confirmado por screenshot. Consequência: com o foco na lateral **nenhuma tool navega** — até `cpu_temperature` falha com `cursor_undetermined` até alguém apertar `right`. Resolver isso exige distinguir aba ativa de cursor na lateral, o que nenhum dos dois caminhos faz hoje. Ainda não resolvido em 2026-08-31.
- **Depende do nível menos confiável do motor.** [`motor-percepcao-interface.md`](motor-percepcao-interface.md) documenta `nav_menu` como sólido (0.76–0.91) e `settings_list` como não confiável. A rota da `cpu_temperature` passa exatamente por um `settings_list`. A taxa real de abstenção ao vivo é desconhecida.
- **Risco herdado agora ativo**: [`caixa-de-deteccao-engloba-barra-de-destaque.md`](../p-specs/caixa-de-deteccao-engloba-barra-de-destaque.md) nomeia HDMI como gatilho de um teto que até então só se manifestava em imagem sintética — e desde 2026-08-20 a entrada é uma capture card HDMI. Se a detecção falhar de forma estranha ao vivo, comparar contra `--engine paddleocr` antes de culpar esta camada.
- A suíte offline cobre um único modelo de BIOS (Positivo) com fixture de imagem, e só para as telas Main/Advanced/Save & Exit — Security, Boot e os submenus de Advanced (Trusted Computing, Device Control, Network Stack, MAPT, Absolute Persistence) não têm fixture de imagem no repositório, então as tools que os leem não têm cobertura de regressão offline, só a validação ao vivo pontual registrada acima.
- **`network_stack` e `mapt` foram lidos ao vivo (2026-08-31) mas não viraram tool nomeada** — dado real, sem `Tool(...)` declarado ainda. Pendência conhecida, não bloqueio.
- **`smart_charging` e `pap` (Positivo Asset Protection), previstos em `labels.py` desde o início, não existem na unidade testada em 2026-08-31** — a varredura completa do menu de Advanced (8 entradas reais) não os contém. Pode ser variação entre unidades/SKUs; os dois continuam declarados como `palpite` para não bloquear um modelo onde de fato existam.
- **Promoção de `trusted_computing`/`device_control`/`network_stack`/`absolute_persistence` a `CONFIRMADO` em `labels.SUBMENUS` é decisão humana pendente** — o conteúdo de cada um já foi visto ao vivo e as tools que os leem já funcionam (a rota usada, `Step`/`move_to`, não depende dessa marca), mas a marca em si não foi trocada, seguindo a disciplina de que promoção é ato humano (ver `labels.py`).
