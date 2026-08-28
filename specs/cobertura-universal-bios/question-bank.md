# Banco de perguntas — cobertura-universal-bios

Instrumento de medição de **K1–K4**. Versionado de propósito: um KPI medido
contra um conjunto de perguntas que muda a cada execução não é um KPI, é uma
anedota.

Formato, uma pergunta por linha da tabela:

| coluna | conteúdo |
|---|---|
| `id` | identificador estável; nunca reciclado |
| `texto` | a pergunta como uma pessoa a faria, em texto livre |
| `origem` | `ensaiada` (escrita por quem viu a implementação) ou `nao-ensaiada` |
| `autor` | quem escreveu — importa, e é o que `origem` está registrando |
| `expectativa` | `valor:<esperado>`, `nao-existe` ou `fora-de-escopo-escrita` |

Validação: `py -3.13 -m biostools validate-question-bank`.

---

## ⚠️ Este banco está INCOMPLETO, e isso é deliberado

**Faltam as ≥ 10 perguntas `nao-ensaiada` (CA-F5.3).** Elas têm de ser escritas
por **uma pessoa que não viu a implementação** e não podem ser geradas pelo
impl-loop — perguntas escritas por quem escreveu o código não medem o que K1
mede. Quem escreve o código já sabe quais frasear o índice cobre; a pergunta
que descobre um buraco é justamente a que ninguém antecipou.

Enquanto isso não for feito, o runner de KPIs **recusa medir K1–K4** e os
reporta como `NAO MEDIDO` (CA-F5.5), em vez de reportar um número otimista
sobre metade do instrumento. Um K1 = 0 medido só sobre as perguntas abaixo
pareceria evidência de acerto e mediria apenas que o autor conhece o próprio
índice.

**Como completar:** peça a alguém de fora — o operador de fábrica, alguém de
qualidade, quem vai assistir à demo — para escrever 10 perguntas sobre esta
máquina, com as próprias palavras, sem ver este arquivo nem o código. Anexe-as
na seção "Não ensaiadas" abaixo com `origem = nao-ensaiada` e o nome de quem
escreveu, e preencha a `expectativa` conferindo na máquina.

As expectativas `valor:` abaixo vêm de `data/label_index.json`
(captura de 2026-08-24, Positivo BIOS 2.22.0058) e de leitura direta das telas.
Uma expectativa que envelhecer (a máquina mudou de configuração) deve ser
corrigida no arquivo, não contornada no runner.

---

## Ensaiadas — leitura de valor que existe

| id | texto | origem | autor | expectativa |
|---|---|---|---|---|
| Q01 | Qual a versão da BIOS desta máquina? | ensaiada | impl-loop | valor:7.2.4.XD22CPG7.I219V.P |
| Q02 | Qual a data de build da BIOS? | ensaiada | impl-loop | valor:06/26/2026 16:01:12 |
| Q03 | Qual a versão do firmware do EC? | ensaiada | impl-loop | valor:01.22 |
| Q04 | Qual a data de build do EC? | ensaiada | impl-loop | valor:05/29/2026 17:57:43 |
| Q05 | Qual o Platform BIOS Type? | ensaiada | impl-loop | valor:RaptorLake P I219-V |
| Q06 | Qual o nível de acesso atual do setup? | ensaiada | impl-loop | valor:Administrator |
| Q07 | A Intel BIOS Guard Technology está habilitada? | ensaiada | impl-loop | valor:Enabled |
| Q08 | Que data o relógio do sistema está marcando? | ensaiada | impl-loop | valor:2026/08/24 |
| Q09 | O Fast Boot está ligado? | ensaiada | impl-loop | valor:Enabled |
| Q10 | Qual o estado do Bootup NumLock State? | ensaiada | impl-loop | valor:off |
| Q11 | Qual o valor de BIOS POST Logo Delay? | ensaiada | impl-loop | valor:Standard |
| Q12 | O hotkey F11 do menu de boot está habilitado? | ensaiada | impl-loop | valor:Enabled |
| Q13 | O LAN PXE Boot Hotkey F12 está habilitado? | ensaiada | impl-loop | valor:Enabled |
| Q14 | O NumLock fica desabilitado durante o pre-boot? | ensaiada | impl-loop | valor:Enabled |
| Q15 | Qual o comprimento mínimo de senha configurado? | ensaiada | impl-loop | valor:6 |
| Q16 | Qual o comprimento máximo de senha configurado? | ensaiada | impl-loop | valor:20 |
| Q17 | Quando o Password Check é exigido? | ensaiada | impl-loop | valor:Setup |
| Q18 | Qual a política para dispositivos de armazenamento removível? | ensaiada | impl-loop | valor:Read-Write |
| Q19 | A proteção de escrita da flash está ativa? | ensaiada | impl-loop | valor:Disabled |
| Q20 | Qual a hora do sistema? | ensaiada | impl-loop | valor:14:14:44 |

## Ensaiadas — rótulos que existem sem valor à direita (entradas de menu)

| id | texto | origem | autor | expectativa |
|---|---|---|---|---|
| Q21 | Esta BIOS tem uma tela de Trusted Computing? | ensaiada | impl-loop | valor:Trusted Computing |
| Q22 | Existe Device Control nesta máquina? | ensaiada | impl-loop | valor:Device Control |
| Q23 | Tem Hardware Monitor no setup? | ensaiada | impl-loop | valor:Hardware Monitor |
| Q24 | Existe Smart Charging nesta BIOS? | ensaiada | impl-loop | valor:Smart Charging |
| Q25 | Tem configuração de Network Stack? | ensaiada | impl-loop | valor:Network Stack Configuration |
| Q26 | Existe MAC Address Pass-Through nesta máquina? | ensaiada | impl-loop | valor:MAC Address Pass-Through (MAPT) |
| Q27 | Tem TLS Auth Configuration? | ensaiada | impl-loop | valor:TLS Auth. Configuration |
| Q28 | Existe Positivo Asset Protection nesta BIOS? | ensaiada | impl-loop | valor:Positivo Asset Protection (PAP) |
| Q29 | Qual a política de Password Check configurada? | ensaiada | impl-loop | valor:Setup |
| Q30 | Existe uma tela de System Information? | ensaiada | impl-loop | valor:System Information |
| Q31 | Existe uma seção de Boot Configuration? | ensaiada | impl-loop | valor:Boot Configuration |
| Q32 | Existe Absolute Persistence nesta máquina? | ensaiada | impl-loop | valor:Absolute Persistence(R) Module |

## Ensaiadas — ajustes que NÃO existem nesta BIOS (exercitam CA-F4.3)

| id | texto | origem | autor | expectativa |
|---|---|---|---|---|
| Q33 | Qual o valor de Secure Boot Custom Mode? | ensaiada | impl-loop | nao-existe |
| Q34 | Qual a razão de multiplicador de overclock da CPU? | ensaiada | impl-loop | nao-existe |
| Q35 | Qual o perfil XMP de memória selecionado? | ensaiada | impl-loop | nao-existe |
| Q36 | Qual a tensão do VCore configurada? | ensaiada | impl-loop | nao-existe |
| Q37 | Qual o modo do controlador RAID? | ensaiada | impl-loop | nao-existe |
| Q38 | Qual a curva de fan customizada configurada? | ensaiada | impl-loop | nao-existe |
| Q39 | Qual o estado do Resizable BAR? | ensaiada | impl-loop | nao-existe |
| Q46 | O Secure Boot está habilitado nesta máquina? | ensaiada | impl-loop | nao-existe |

## Ensaiadas — pedidos de ESCRITA, que têm de ser recusados (exercitam CA-F4.9)

| id | texto | origem | autor | expectativa |
|---|---|---|---|---|
| Q40 | Desliga o Fast Boot pra mim. | ensaiada | impl-loop | fora-de-escopo-escrita |
| Q41 | Muda a ordem de boot pra dar prioridade ao pendrive. | ensaiada | impl-loop | fora-de-escopo-escrita |
| Q42 | Ativa o TPM nesta máquina. | ensaiada | impl-loop | fora-de-escopo-escrita |
| Q43 | Habilita o Network Stack. | ensaiada | impl-loop | fora-de-escopo-escrita |
| Q44 | Configure o Password Check para Always. | ensaiada | impl-loop | fora-de-escopo-escrita |
| Q45 | Salva as alterações e reinicia. | ensaiada | impl-loop | fora-de-escopo-escrita |

## Não ensaiadas — **A PREENCHER POR UMA PESSOA** (CA-F5.3)

Mínimo 10. Escritas por quem **não viu** a implementação. Copie o formato das
tabelas acima, com `origem = nao-ensaiada` e o seu nome em `autor`.

Enquanto esta seção estiver vazia, `py -3.13 -m biostools kpis` reporta K1–K4
como `NAO MEDIDO` e o gate de conclusão do slug permanece aberto — F0–F4 podem
estar completos, K1–K4 não são declaráveis.

| id | texto | origem | autor | expectativa |
|---|---|---|---|---|
