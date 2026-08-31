# Manual da estação de leitura de BIOS

Guia de referência para quem vai **montar a estação, apresentar o sistema ou só entender o que ele faz** — não é exclusivo de quem já acompanhou o projeto. Cobre a arquitetura de três máquinas, como montar uma estação do zero, todas as perguntas que o sistema hoje sabe responder, e o que fazer quando algo dá errado ao vivo.

Complementa (não substitui) [`PROCESSO_OCR.md`](PROCESSO_OCR.md) (como a leitura da tela funciona por dentro) e o F-spec [`camada-de-tools-consulta-bios.md`](../specs/f-specs/camada-de-tools-consulta-bios.md) (a lista técnica completa de tools). Este documento é sobre **usar** o sistema, não sobre como ele é implementado.

## O que o sistema faz, em uma frase

Alguém pergunta em português, em voz normal ("qual a temperatura da CPU?"); o sistema lê a tela de uma BIOS de verdade por câmera, aperta as teclas necessárias por um cabo físico, e responde com o valor real — sem digitar nada na BIOS, sem ninguém abrir o Setup manualmente.

## As três máquinas

O sistema roda em três máquinas separadas, cada uma com um papel:

| Máquina | Papel |
|---|---|
| **Intermediária** (Windows) | Onde o código roda. Tem a câmera (lê a tela) e o cabo atuador (aperta teclas). É onde a pessoa digita a pergunta. |
| **BIOS alvo** | A máquina sendo testada/apresentada. O cabo se conecta nela como se fosse um teclado USB comum — ela não sabe que está sendo operada por software. |
| **IA** | Roda o modelo de linguagem (Lemonade Server) que interpreta a pergunta, escolhe qual leitura fazer, e escreve a resposta em português. Fica sempre numa máquina separada, com NPU dedicada. |

A intermediária é o único ponto que fala com as outras duas — a BIOS nunca fala direto com a IA, e quem pergunta nunca toca em nenhuma das duas.

```
  pessoa                intermediária              BIOS alvo
    │  pergunta (pt-br)      │                          │
    ├────────────────────────►                          │
    │                        │── câmera USB: lê a tela ─►│
    │                        │── cabo COM: envia teclas ►│
    │                        │                          │
    │                        │      máquina de IA
    │                        │── rede: pergunta + tools ►│
    │                        │◄── resposta em texto ─────│
    │◄── resposta ────────────                          │
```

## Montando uma estação do zero

Sequência recomendada — nessa ordem, porque cada fase depende da anterior estar confirmada:

### 1. Máquina de IA

```bash
lemonade backends install flm:npu
lemonade pull qwen3.6-moe-35b-a3b-FLM
```

Esse é o modelo que o assistente usa de fato (mais preciso na escolha de tool, mais lento — ver o porquê em `biostools/assistant.py`, comentário de `ASSISTANT_MODEL`). É um download grande; comece por ele com antecedência, não na véspera da apresentação.

Por padrão o Lemonade escuta só em `127.0.0.1` (loopback) — inacessível de outra máquina. Para uma demo ao vivo, é mais confiável reconfigurar para escutar na rede do que depender de um túnel SSH (mais uma coisa que pode cair no meio da apresentação):

```bash
lemonade config set host=0.0.0.0
```

Confirme que responde **de outra máquina**, não da própria:

```bash
curl http://<ip-da-maquina-de-ia>:13305/api/v1/models
```

### 2. Máquina intermediária

```bash
py -3.13 -m pip install -r requirements.txt
py -3.13 test_biostools.py
```

O segundo comando roda a suíte offline — sem câmera, sem cabo. Se não terminar em `tudo passou`, o problema é do código/ambiente, resolve isso antes de tocar em qualquer hardware.

Depois, confirme que a máquina realmente enxerga a câmera e o cabo:

```bash
py -3.13 -c "from capture import list_camera_devices; print(list_camera_devices())"
py -3.13 -c "from actuator import list_serial_ports; print(list_serial_ports())"
```

### 3. Ligar as pontas

`assistant.ask(pergunta, sessao, host=..., port=...)` aceita o endereço da máquina de IA como parâmetro — não precisa editar código, só apontar para o IP certo.

### 4. Bancada física

- **Câmera perto e alinhada com a tela**, não enquadrando o monitor inteiro de longe — já aconteceu de o OCR ler zero palavras com o texto pequeno demais em pixels.
- **Cabo USB-KM232**: ponta USB na máquina BIOS alvo (aparece pra ela como teclado comum, sem driver); ponta serial no adaptador USB-serial, e este na máquina intermediária.
- BIOS alvo ligada e parada no Setup (tela Main visível) antes de começar.

## O que perguntar

Qualquer pergunta em português normal. A IA escolhe sozinha qual leitura fazer — quem pergunta não precisa saber nome de tool nenhuma.

**Para abrir**, as duas melhores — mostram câmera, OCR e cabo funcionando juntos em tempo real, com um número que muda a cada leitura:

- "Qual a temperatura da CPU?"
- "Qual a rotação do cooler?"

**Sistema**: versão e data de build da BIOS · versão e data de build do EC · nome do produto, fabricante e número de série · data e hora configuradas · endereço MAC · quantidade e frequência da memória RAM · versão do Intel Management Engine.

**Segurança**: o TPM está habilitado, e em que estado · a BIOS pede senha só no Setup ou também no boot · a proteção de escrita da flash está ativa, e o downgrade de BIOS é permitido · política para armazenamento USB removível · o Absolute Persistence está ativo, versão e status da interface.

**Boot**: Fast Boot habilitado · ordem de boot configurada · estado do NumLock na inicialização · tempo que o logo fica visível no POST · atalho de boot F11 e PXE após Wake on LAN · boot por dispositivo removível, checagem S.M.A.R.T. e reflash do ME.

**Energia, vídeo e periféricos**: quais eventos acordam a máquina (LAN, PCI/PCIE, teclado/mouse, RTC) · USB Charger habilitado · modo do controlador SATA · display primário e memória de vídeo alocada (GTT/Aperture/DVMT) · virtualização (VT-d/VT-x) habilitada · Audio DSP habilitado · quais dispositivos onboard estão ligados (vídeo, áudio, SATA, M.2, leitor de cartão).

**Se a pergunta não tiver tool nomeada para o assunto**, o sistema ainda tenta: primeiro no índice de rótulos já colhido desta máquina, depois varrendo a tela ao vivo antes de desistir. Funciona para qualquer ajuste real da BIOS, mesmo bem específico — "o Network Stack está habilitado?", "qual o tempo de espera do PXE Boot?".

**Se o ajuste realmente não existir nesta BIOS**, a resposta é honesta sobre isso — "não existe nesta máquina" é uma resposta certa, não uma falha do sistema. Vale enquadrar isso como recurso na hora de apresentar: o sistema nunca chuta um valor que não leu.

### Evitar por enquanto

"Quais opções tem no menu principal?" e "o que a tela Main mostra?" (as tools `main_menu`/`main_info`) estão bloqueadas por um problema conhecido: quando o cursor está na barra lateral, o motor de percepção não consegue distinguir a aba ativa do cursor — as duas desenham uma barra escura quase idêntica. Detalhe técnico em [`camada-de-tools-consulta-bios.md`](../specs/f-specs/camada-de-tools-consulta-bios.md#questões-em-aberto).

## Se algo der errado ao vivo

**A IA demora para responder.** O modelo principal roda localmente, sem depender de internet, e pode levar de alguns segundos até ~30s numa pergunta mais elaborada. Não é travamento — vale narrar isso em vez de esperar em silêncio.

**A IA não responde de jeito nenhum.** Sintoma: erro de "chamada ao modelo falhou". Normalmente é a máquina de IA inacessível pela rede (confira o `host=0.0.0.0` da Fase 1, ou se o túnel SSH caiu). Enquanto isso, cada tool ainda pode ser chamada diretamente (sem passar pela IA) — `run_tool(nome, sessao)` devolve o valor bruto sem narração em português.

**O cabo para de responder.** Aconteceu de verdade numa sessão de testes (`CableNotResponding`) — a porta COM continuava visível pro Windows, mas o protocolo do cabo parou de responder. Causa mais provável: a ponta USB do cabo se soltou, ou a máquina BIOS alvo entrou em suspensão. Reconectar a ponta USB e confirmar que a máquina alvo está acordada resolve na maioria dos casos.

**A resposta parece errada ou incompleta.** O sistema nunca inventa um valor: se a narração da IA não bate palavra por palavra com o que a tool leu da tela, ele descarta a narração e mostra o texto bruto da leitura em vez disso. Uma resposta "estranha" tem mais chance de ser uma leitura real da tela do que uma alucinação — vale conferir a tela antes de assumir que é bug.

## Antes da apresentação

- **Rode o checklist inteiro na estação que vai ser usada de verdade, com antecedência — não na véspera.** Uma BIOS "idêntica" em outra unidade física já se comportou de forma sutilmente diferente numa sessão de testes deste projeto (tempo de rolagem de página variou por página); só apareceu rodando contra o hardware real. Melhor descobrir isso com tempo de corrigir.
- Prefira cabo de rede a wifi entre a intermediária e a máquina de IA, se der — é o ponto mais frágil se a rede cair no meio de uma pergunta.
- Tenha uma ordem de perguntas em mente (abrir com sensor ao vivo, aprofundar por assunto) em vez de ler a lista solta — fica mais natural e mais fácil de recuperar se algo falhar no meio.
