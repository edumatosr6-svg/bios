# Cobertura universal de perguntas sobre a BIOS

## Objetivo

Hoje o sistema responde bem as perguntas que têm uma **tool nomeada** escrita
para elas (`cpu_temperature`, `bios_info`, `main_info`, `main_menu`). Fora
dessa lista, a resposta depende de um caminho genérico (`goto_screen`) que
cobre pouco.

O objetivo deste slug é inverter isso: **qualquer pergunta sobre a BIOS da
máquina sob teste deve ser respondida, exista ou não uma tool nomeada para
ela.** A tool nomeada passa a ser uma camada de velocidade e confiabilidade
sobre as perguntas frequentes, não o mecanismo de cobertura.

Contexto: isso é preparação para uma apresentação demo, em que um operador
faz perguntas específicas em texto livre e espera respostas corretas. Uma
pergunta não ensaiada não pode virar "não achei".

## Os três buracos que causam a falta de cobertura

Levantados sobre o código atual, com evidência:

1. **O leitor genérico é cego abaixo da dobra.** `AllFields.read`
   (`biostools/registry.py`) lê uma única leitura de tela, sem rolar. O
   `study_scroll_map.py` mediu ao vivo (2026-08-24) que a página Main tem
   **73 linhas únicas contra ~31 visíveis de uma vez**. O caminho genérico
   enxerga hoje menos da metade da tela Main; um campo abaixo da dobra
   produz "não achei" mesmo estando presente.

2. **Submenu é inalcançável genericamente.** `goto_screen` só aceita
   `TOP_LEVEL_SCREENS` (`biostools/navigate.py`). Hardware Monitor,
   Trusted Computing, Device Control, Network Stack, MAPT, Smart Charging,
   TLS Auth e PAP vivem **dentro** da Advanced — e é onde estão a maioria
   dos ajustes sobre os quais alguém pergunta. A temperatura da CPU só é
   respondível hoje porque existe uma tool nomeada com rota fixa até lá.

3. **O modelo adivinha em qual tela procurar.** O roteamento do caminho
   genérico depende de dicas escritas à mão na descrição do `goto_screen`
   ("Fast Boot fica em boot, senhas em security"). Não escala e é o que
   erra numa pergunta não ensaiada.

O buraco 3 se resolve como consequência de resolver 1 e 2: varrer tudo
(todas as telas, descendo nos submenus, rolando cada página até o fim)
produz um **índice de todo rótulo que existe nesta máquina**, e o índice é
o que substitui o palpite.

## Features desejadas

### F1 — Leitura de página inteira (rolagem)

O leitor genérico deve ler **toda** a página, não só o que está visível.
Rolagem por teclado (PgDn/PgUp), que move um screenful por vez e para de
forma confiável nas pontas — confirmado ao vivo em 2026-08-24 sobre a
página Main.

Detalhe carregador, já documentado em `study_scroll_map.py`: **uma
coordenada só é válida na posição de rolagem em que foi capturada.**
Qualquer estrutura que guarde posição precisa guardar o índice de tela
junto; guardar coordenada nua produz clique confiante na linha errada.

O leitor tem que saber que chegou ao fim da página em vez de rolar um
número fixo de vezes, e não pode duplicar linhas que aparecem em duas
telas consecutivas por sobreposição.

### F2 — Alcance genérico a submenus

O caminho genérico deve alcançar uma tela de submenu (um nível abaixo de
uma tela de topo), não só as telas da barra lateral. Deve reaproveitar a
navegação ancorada existente (`navigate.enter_main_menu_screen`) para
chegar à tela de topo, e de lá descer até o submenu nomeado.

O submenu tem que ser identificado por conteúdo/rótulo declarado, não por
posição fixa na lista — a ordem dos itens muda entre modelos de BIOS.

### F3 — Índice de rótulos da máquina

Um tour completo, rodado na bancada contra o hardware real, que visita
todas as telas de topo, desce em cada submenu, rola cada página até o fim,
e salva um índice do tipo *rótulo → onde ele está* (tela, submenu, posição
de rolagem).

Requisitos:
- É **material colhido de hardware real**, nunca inventado. Segue a mesma
  disciplina de `biostools/labels.py`: o que foi visto de verdade é
  marcado como confirmado; o resto não entra.
- É um **artefato versionado**. O projeto já perdeu um corpus de fixtures
  exatamente por não commitar (ver
  `docs/specs/p-specs/fixture-de-teste-nunca-versionada.md`), e a demo
  inteira vai depender deste índice.
- A tela `save_and_exit` **não é visitada** por padrão, pela mesma razão
  que `study_menu_tour.py` já a exclui: todo controle dela compromete ou
  abandona configuração.
- O tour não pode alterar nenhum ajuste — só teclas de navegação.

### F4 — `find_setting`: o caminho universal de resposta

Uma tool que recebe o termo da pergunta, procura no índice de F3, navega
até a tela (usando F2 se for submenu), rola até a posição certa (F1) e lê
o valor ali.

É o caminho que responde quando nenhuma tool nomeada existe.

Comportamento exigido quando **não** encontra: a resposta tem que ser a
afirmação honesta **"esse ajuste não existe na BIOS desta máquina"**,
acompanhada de onde procurou — e não um "não achei" ambíguo. As duas
frases descrevem situações diferentes e a diferença importa: uma é
conhecimento, a outra é falha. O índice é o que permite distinguir.

Continua valendo a regra do projeto: **nunca casar com a linha mais
parecida**. Se o termo não bate com nada declarado, abstém-se. Em um
sistema de leitura de fábrica, um casamento errado (a temperatura do
sistema reportada como a da CPU) é um erro silencioso sobre o qual o
operador age; "não encontrei" é barulhento e inofensivo.

## Restrições que atravessam tudo

- **Somente leitura.** `SAFE_KEYS` (`biostools/registry.py`) bloqueia `+`,
  `-`, F10 e `y` por projeto. Nada neste slug pode alargar isso. Perguntas
  do tipo "desliga o Fast Boot" devem ser recusadas de forma clara — é
  fronteira deliberada, não limitação a contornar.
- **Abstenção é conteúdo de primeira classe.** Resposta confiantemente
  errada é pior que ausência de resposta — a arquitetura já trata assim
  (`docs/architecture/PERCEPTION_PIPELINE_SPEC.md` §2).
- **Rótulos declarados, nunca adivinhados** (`biostools/labels.py`).
- **Uma sessão serve muitas tools** (`biostools/session.py`) — nada aqui
  pode reabrir câmera ou recarregar modelo de OCR por chamada.
- Toda leitura continua verificada contra o que a tela mostra depois da
  tecla, nunca assumida.

## Fora de escopo

- Alterar qualquer ajuste da BIOS (permanece bloqueado por `SAFE_KEYS`).
- Visitar ou operar a tela `save_and_exit`.
- As tools nomeadas adicionais (`system_identity`, `security_status`,
  `boot_config`, `thermal_status`, `tpm_status`) e a tool composta
  `check_config` de aprovação/reprovação por perfil esperado. São
  desejadas, mas são outro slug — este aqui é a **cobertura**, aquele é a
  **camada rápida** em cima dela.
- Suportar um quarto modelo de BIOS. O alvo é a máquina da demo (Positivo,
  BIOS 2.22.0058).

## KPIs pretendidos

O critério que importa para a apresentação é cobertura medida, não features
entregues. A ideia é montar um banco de perguntas reais sobre esta máquina
(incluindo perguntas não ensaiadas, escritas por outra pessoa) e medir:

- fração respondida corretamente;
- fração que resulta em abstenção honesta;
- fração que resulta em resposta errada — que deve ser **zero**, e é o
  número mais importante dos três;
- tempo até a resposta (a demo é ao vivo; uma resposta correta em 90s não
  serve).
