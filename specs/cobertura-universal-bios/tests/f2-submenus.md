# Testes — F2: Alcance genérico a submenus

Sessão fake como em `f1-leitura-pagina-inteira.md`, mais um stub de
`navigate.enter_main_menu_screen` que registra a tela pedida e devolve
sucesso/falha controlados.

## CT-F2.1 — Caminho feliz: tela de topo, depois submenu
- **Dado** `SUBMENUS["hardware_monitor"] == "advanced"` e uma tela fake de Advanced
  contendo a linha `"Hardware Monitor"`
- **Quando** a navegação para `hardware_monitor` executa
- **Então** `enter_main_menu_screen` foi chamada com `"advanced"`
- **E** o cursor foi movido até a linha e `enter` foi enviado
- **E** o resultado é sucesso

## CT-F2.2 — Submenu identificado por conteúdo, não por posição
- **Dado** duas telas fake de Advanced com **ordem diferente** dos mesmos itens
- **Quando** a navegação para `hardware_monitor` executa em cada uma
- **Então** ambas alcançam o item correto
- **E** o número de passos difere entre elas (prova que a posição não é assumida)

## CT-F2.3 — Grafia alternativa declarada
- **Dado** uma tela de Advanced que escreve `"H/W Monitor"` (grafia declarada em
  `labels.SCREENS["hardware_monitor"]`)
- **Quando** a navegação para `hardware_monitor` executa
- **Então** o item é encontrado

## CT-F2.4 — Grafia NÃO declarada não é adivinhada
- **Dado** uma tela de Advanced que escreve `"Sensores do Sistema"` (não declarada)
- **Quando** a navegação para `hardware_monitor` executa
- **Então** o resultado é falha explícita ("não encontrei o submenu")
- **E** nenhum `enter` foi enviado
- (Nunca casar com a linha mais parecida — R3.)

## CT-F2.5 — Submenu desconhecido no mapa
- **Dado** o pedido de submenu `"overclocking"`, ausente de `SUBMENUS`
- **Quando** a navegação executa
- **Então** o resultado é falha nomeando os submenus conhecidos
- **E** `enter_main_menu_screen` não foi chamada

## CT-F2.6 — Chegada verificada
- **Dado** que o `enter` foi enviado mas a tela resultante **não** contém nenhuma
  grafia declarada de `hardware_monitor`
- **Quando** a navegação executa
- **Então** o resultado é falha ("não confirmei a chegada"), não sucesso
- (R5: verificado, nunca assumido.)

## CT-F2.7 — Submenu abaixo da dobra
- **Dado** uma tela de Advanced onde `"Smart Charging"` só aparece no screenful 2
- **Quando** a navegação para `smart_charging` executa
- **Então** o reader de F1 é usado para rolar até encontrá-lo
- **E** o item é alcançado

## CT-F2.8 — Falha em chegar à tela de topo aborta cedo
- **Dado** um `enter_main_menu_screen` que devolve falha com motivo `"sidebar coberta
  por diálogo"`
- **Quando** a navegação para `hardware_monitor` executa
- **Então** o resultado é falha propagando esse motivo
- **E** nenhuma tecla `enter` foi enviada depois disso

## CT-F2.9 — `save_and_exit` é recusada
- **Dado** um pedido cujo destino ou pai é `save_and_exit`
- **Quando** a navegação executa
- **Então** o resultado é recusa explícita
- **E** nenhuma tecla foi enviada (R6)

## CT-F2.10 — Repetibilidade
- **Dado** uma sessão fake
- **Quando** a navegação para `hardware_monitor` executa duas vezes seguidas com
  restauração ligada
- **Então** ambas têm sucesso
- **E** entre elas foi enviado `esc` para fechar o submenu aberto
- (Regressão do bug documentado em `Tool.run`: `cpu_temperature` funcionava uma vez só.)

## CT-F2.11 — Somente `SAFE_KEYS`
- **Dado** qualquer cenário acima
- **Então** `set(session.pressed) ⊆ registry.SAFE_KEYS`

## CT-F2.12 — Provenance `palpite`: um caso por caminho (CA-F2.1a)

Quatro asserções distintas sobre a **mesma** entrada `SUBMENUS` marcada `"palpite"`:

### CT-F2.12a — F2 direta navega, com aviso
- **Quando** a navegação é chamada diretamente com esse submenu
- **Então** ela navega normalmente
- **E** o resultado traz em `notes` "submenu não confirmado em hardware"

### CT-F2.12b — F3 tour não visita
- **Quando** o tour executa
- **Então** esse submenu não é visitado e não gera entradas no índice
- **E** aparece em `skipped` com motivo `"provenance=palpite"`

### CT-F2.12c — F4 abstém-se
- **Dado** uma entrada de índice apontando para uma página desse submenu
- **Quando** `find_setting` tenta navegar até ela
- **Então** o resultado é abstenção, não navegação

### CT-F2.12d — K6 não conta
- **Então** esse submenu não entra na contagem de submenus alcançados do KPI K6

## CT-F2.13 `[BANCADA]` — Alcance real (KPI K6)
- **Dado** a máquina alvo
- **Quando** a navegação é executada para cada submenu declarado de Advanced
- **Então** ≥ 8 deles são alcançados e verificados
