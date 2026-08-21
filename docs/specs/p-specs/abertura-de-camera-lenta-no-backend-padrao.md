# Abrir a câmera no backend padrão do OpenCV custa 25-27s no Windows

## O problema

`cv2.VideoCapture(0)` **demora 25 a 27 segundos para retornar** nesta máquina. Não é travamento nem erro: a chamada devolve um dispositivo funcionando, só que dezenas de segundos depois. O sintoma que chega ao usuário é "mando o comando e demora muito" — todo o custo aparece antes de qualquer trabalho útil começar.

Medido em 2026-08-20 contra a capture card USB-HDMI, três execuções consistentes:

| Backend | Abrir | Nitidez (variância do Laplaciano) | Resolução obtida |
|---|---|---|---|
| MSMF (padrão do OpenCV no Windows) | **25.8s** | 534.9 | 1280x720 |
| DirectShow (`cv2.CAP_DSHOW`) | **0.2s** | **653.9** | 1280x720 |

DirectShow é ~100x mais rápido para abrir **e** entrega um quadro 22% mais nítido, na mesma resolução. **Não há trade-off a ponderar** — é ganho nos dois eixos, o que é raro o bastante para merecer registro: a suspeita natural seria que o backend rápido estivesse entregando imagem pior, e a medição diz o contrário.

O custo se multiplica onde mais dói: `capture.list_camera_devices()` sonda os índices 0..5, pagando a abertura em cada um. Com MSMF isso é mais de dois minutos só para listar as câmeras.

## Onde ele mora

Qualquer ponto que abra câmera. Hoje:

- [`../f-specs/camada-de-tools-consulta-bios.md`](../f-specs/camada-de-tools-consulta-bios.md) — `biostools/session.py`, **corrigido**;
- `capture.py` (`capture_from_camera`, `list_camera_devices`) — **corrigido**;
- `gui.py`, `watcher.py`, `perception/run.py`, `bios_navigate_demo.py` — **ainda usam `cv2.VideoCapture` direto e continuam pagando os 25s**.

## Por que existe

O OpenCV no Windows escolhe Media Foundation (MSMF) como backend padrão. A enumeração/negociação de formato do MSMF é lenta a frio para este dispositivo. Não é defeito do OpenCV nem da capture card — é a combinação, e por isso não se resolve trocando de câmera.

Já havia registro parcial disso no histórico do projeto ("MSMF cold-start pode levar 20-60s na primeira abertura"), mas tratado como *quirk a tolerar*, não como problema com correção conhecida. A medição acima mostra que havia correção o tempo todo.

## Como evitar / mitigar

Abrir com `cv2.CAP_DSHOW` quando a fonte for um **índice de dispositivo** e a plataforma for Windows. Implementado em `capture.py::open_camera`, que os pontos corrigidos acima usam no lugar de `cv2.VideoCapture`.

Duas restrições que a implementação respeita e que não devem ser removidas:

- **Só para índice numérico.** Uma fonte URL (stream MJPEG) é atendida por outro backend, e passar `CAP_DSHOW` junto simplesmente falha.
- **Com retorno ao padrão.** Se o DirectShow não abrir o dispositivo — algumas câmeras virtuais são MSMF-only — a chamada simples é refeita. O pior caso vira o comportamento antigo, não uma falha.

Os pontos ainda não corrigidos passam a ser uma linha de mudança: trocar `cv2.VideoCapture(x)` por `open_camera(x)`.

## Status

**Mitigado onde a camada de tools usa; aberto no resto — 2026-08-20.** Startup da camada de tools caiu de ~28s para ~2s até estar pronta para ler. Os outros pontos de entrada não foram alterados nesta sessão por não terem sido exercitados junto; a correção é a mesma linha em cada um.
