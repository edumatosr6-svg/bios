# Webcam UGREEN 4K

## O que é
Câmera USB usada para capturar a tela da BIOS durante os testes deste projeto — leitura contínua via `capture.py`, consumida por `gui.py`, `watcher.py` e `perception/run.py`.

## Por que essa e não outra
Não foi avaliada contra câmeras alternativas nesta sessão — é o hardware físico disponível para teste. O que foi avaliado, pela primeira vez, foi **como configurá-la**: nenhum arquivo do projeto (`capture.py`, `gui.py`, `watcher.py`) jamais tinha setado resolução explicitamente antes desta sessão; todo teste histórico do projeto rodou no default do driver — tipicamente 640x480, baixo demais para texto de BIOS.

Medição de nitidez (variância do Laplaciano) apontando para uma tela real de BIOS, comparando os dois modos testados:

| Modo | Nitidez medida (variância do Laplaciano) |
|---|---|
| 1280x720 | 612 |
| 1920x1080 | 85 |

Achado contraintuitivo: **resolução mais alta não é sempre melhor.** O modo 1080p desta câmera específica é interpolado/borrado; 720p é a resolução nativa real dela. Confirmado visualmente comparando os dois PNGs capturados — a diferença é grosseira, não sutil, não é um efeito de medição.

## Como é usada aqui
- Resolução padrão do projeto fixada em **1280x720** com base nessa medição — `perception/run.py` (`--resolution`, default `"1280x720"`) e `gui.py` (`--resolution`, default `f"{REQUESTED_WIDTH}x{REQUESTED_HEIGHT}"`). O código comenta explicitamente que esse valor deve ser remedido se a câmera de produção da fábrica for diferente desta — é uma propriedade medida desta câmera, não uma constante universal do sistema.
- MJPG (codec comprimido) é usado só como *fallback*, aplicado apenas quando a resolução pedida é recusada sem ele (`perception/run.py::_request_resolution`) — porque compressão JPEG cria artefatos exatamente nas bordas de glifos, o que prejudica o OCR. O caminho sem compressão é preferido sempre que a câmera aceita a resolução pedida assim.
- Detecção de câmera invalidada pelo Windows: depois de N leituras falhas seguidas com o erro MSMF `-1072873821` (`MF_E_VIDEO_RECORDING_DEVICE_INVALIDATED`), a GUI passa a avisar o usuário a desconectar/reconectar o cabo USB em vez de ficar tentando ler silenciosamente.
- Listagem de nomes de câmera (`capture.py`, via PowerShell) passou a consultar só a classe Plug-and-Play `Camera`, e não mais `Camera` **e** `Image` juntas — `Image` inclui scanners de rede, o que causava descompasso entre a contagem de dispositivos de vídeo e a lista de nomes retornada, e por segurança descartava todos os nomes quando isso acontecia.

## Limitações conhecidas
- A medição 720p vs. 1080p é específica desta câmera (UGREEN 4K); não generaliza para outro hardware sem remedir.
- **A listagem de câmeras pode mostrar o nome desta câmera ao lado do índice errado** — os nomes do Windows são casados com os índices do OpenCV por posição, e em 2026-08-14 `--list-cameras` rotulou esta câmera como índice 1 quando ela era o índice 0, fazendo abrir a webcam integrada no lugar dela. Ver `../p-specs/rotulo-de-camera-desalinhado-do-indice-opencv.md`.
- Só os dois extremos de resolução disponíveis foram comparados — nenhuma resolução intermediária (ex.: 960x540) foi medida, então não se sabe se 720p é o ótimo ou só o melhor dos dois pontos testados.

## Status
Em uso — 2026-08-06. Resolução 1280x720 fixada como padrão do projeto nesta sessão, substituindo o default de driver não configurado que era usado até então.
