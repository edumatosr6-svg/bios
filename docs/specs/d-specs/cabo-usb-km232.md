# Cabo USB-KM232 (Hagstrom Electronics)

## O que é

Cabo emulador de teclado e mouse: a ponta USB entra na máquina alvo e se apresenta como um **teclado/mouse USB HID padrão** (sem driver, e funciona dentro da BIOS/UEFI, que suporta HID nativamente); a ponta RS-232 recebe bytes do computador de controle e os traduz em teclas e ações de mouse na máquina alvo. É a metade **atuadora** do projeto — até 2026-08-20 tudo aqui era somente leitura.

## Por que essa e não outra

Foi a peça comprada pelo usuário; não houve comparação de alternativas. O que a validação encontrou, e que importa mais que a escolha:

**O cabo em mãos é o USB-KM232, não o USB-ASC232** — produtos irmãos, fisicamente idênticos, mesmos conectores, e **a mesma tabela de códigos de tecla**. A confusão custou uma sessão inteira de diagnóstico: o utilitário oficial `USBASC232.EXE` (baixado de `hagstromelectronics.com/software/USBASC232_PCAPP.zip`, link correto para o *ASC232*) repetia "No USB-ASC232 device was detected" mesmo com o cabo ligado direto na porta USB do PC de desenvolvimento e o programa rodando como Administrador. Nenhuma das duas coisas era o problema: aquele utilitário simplesmente nunca reconheceria este modelo.

Identificação definitiva pelo próprio Windows:

```powershell
Get-PnpDevice | Where-Object { $_.InstanceId -eq '<id do dispositivo>' } |
  Get-PnpDeviceProperty -KeyName DEVPKEY_Device_BusReportedDeviceDesc
```

devolveu literalmente `Hagstrom Electronics, Inc. USBKM232`. **Se "no device detected" aparecer de novo, cheque isso antes de suspeitar de fiação ou driver.**

Diferença prática entre os dois modelos:

| | USB-ASC232 | **USB-KM232 (este)** |
|---|---|---|
| Modos | ASCII / ASCII estendido / Key Number, selecionáveis | **Nenhum — sempre key number** |
| Configuração | via `USBASC232.EXE`, gravada no cabo | **Nenhuma** |
| Protocolo serial | configurável | **Fixo: 9600, 8, N, 1** |
| Handshaking | RTS/CTS por hardware | **In-band: complemento de 1 por byte** |
| Mouse | pacote de 4 bytes com delta relativo | comandos de passo discreto, 1 byte |

Ou seja: **este cabo não precisa de configuração nenhuma**. Abrir a porta serial a 9600/8/N/1 e mandar bytes.

## Como é usada aqui

`actuator.py`, classe `BiosActuator` — context manager que abre a porta, limpa o buffer do cabo ao entrar e ao sair. Métodos: `press`, `combo`, `navigate`, `key_down`/`key_up`, `led_status`, `mouse_move`/`mouse_scroll`/`mouse_click`. Consumido pela camada de tools via `BiosSession` (ver [`camada-de-tools-consulta-bios.md`](../f-specs/camada-de-tools-consulta-bios.md)).

Cada tecla tem um código *make* (pressionar) e um *break* (soltar) = make + 0x80. Um make **nunca** é solto sozinho — `press()`/`combo()` sempre emparelham os dois, senão a tecla fica presa na máquina alvo e passa a repetir.

`KEY_CODES` foi transcrita da tabela oficial impressa no manual (página 6 do KM232; idêntica valor a valor à página 7 do ASC232). **Não re-derive essa tabela de uma extração `pdftotext` do manual** — a diagramação em colunas embaralha o texto e o resultado sai errado. A leitura correta foi feita renderizando a página como imagem via PyMuPDF (`fitz`), já que `pdftoppm`/poppler não está instalado nesta máquina (só o `pdftotext` que vem com o Git).

Handshaking merece atenção porque não é o usual: o cabo responde quase todo byte recebido com o **complemento de 1** dele, e é essa resposta que significa "processei, pode mandar o próximo". `BiosActuator._send` lê e valida essa resposta e levanta `CableNotResponding` no timeout — o que dá confirmação real de entrega, ao contrário de escrever numa serial sem retorno.

Fiação em produção (a ponta serial precisa de um adaptador porque PCs modernos não têm porta serial):

```
[PC da BIOS] ⇐USB⇐ [KM232] ⇐serial⇒ [adaptador USB-serial] ⇒USB⇒ [PC de controle]
```

O adaptador em uso é um Prolific PL2303GT, que enumera como **COM3** nesta máquina. `pyserial>=3.5` em `requirements.txt`.

## Limitações conhecidas

- **A ponta USB precisa estar num PC ligado** — o cabo é alimentado por ela (5V, máx. 100mA). Sem isso a lógica não responde pela serial.
- **Máximo ~6 teclas simultâneas em estado make** (limite do buffer de teclado USB); `combo()` não impõe isso.
- **Mouse sem coordenada absoluta**: só passos discretos em pequeno ou grande, relativos à posição atual. Posicionar num ponto específico exige levar o cursor a um canto conhecido primeiro. Nenhuma tool usa mouse hoje.
- **`CableNotResponding` é ambíguo entre causas**: ponta USB sem energia, porta COM errada, ou cabo com defeito produzem o mesmo timeout.
- A tabela de teclas embutida é a **US**; existe uma internacional no manual, não transcrita.

## Status

**Em uso — 2026-08-20.** Validado ponta a ponta em hardware real no mesmo dia: `clear_buffer()` e `led_status()` responderam, e `press("down")` **moveu de fato a seleção do menu da BIOS**, confirmado visualmente pelo usuário. Primeira atuação por software sobre a máquina alvo neste projeto.

Exercitado até agora: `press("down")` e `press("enter")`. As demais teclas, `combo()`, `navigate()` e todos os comandos de mouse estão implementados mas **não foram testados contra hardware**.
