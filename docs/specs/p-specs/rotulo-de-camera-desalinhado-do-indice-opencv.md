# `--list-cameras` mostra o nome errado ao lado do índice de câmera

## O problema
`list_camera_devices()` em `capture.py` (~linha 40) **reporta o rótulo errado para cada índice de câmera** quando a ordem de enumeração do OpenCV não coincide com a ordem de enumeração do Windows.

Observado na prática em 2026-08-14, durante a preparação do estudo de votação de OCR (`../../studies/estudo-votacao-ocr-multi-frame.md`):

```
python -m perception.run --list-cameras
0: Integrated Camera
1: UGREEN Camera 4K
```

Na máquina em questão, a realidade é o inverso: **o índice 0 é a câmera UGREEN apontada para a BIOS** e o índice 1 é a webcam integrada.

**Consequência concreta, não hipotética**: seguir o rótulo abre a webcam apontada para a pessoa em vez da câmera apontada para a BIOS. Aconteceu nesta sessão. Todo o estudo teve que ser rodado com `--camera-source 0`, contrariando o que a própria listagem do projeto indicava.

## Onde ele mora
`capture.py::list_camera_devices()`, e por extensão todo consumidor da listagem: `perception/run.py --list-cameras`, e a escolha de câmera na GUI (`gui.py`). A câmera em si está documentada em `../d-specs/webcam-ugreen-4k.md`.

## Por que existe
A função obtém duas listas independentes e as casa **por posição**:

- `working` — índices `0..max_index-1` que o OpenCV abre e dos quais lê um frame de fato;
- `names` — nomes vindos do Windows, via PowerShell (`Win32_PnPEntity` com `PNPClass = 'Camera'`, ver `_windows_camera_names()`);

e depois faz `zip(working, names)`. Nada garante que a ordem de enumeração do OpenCV (backend MSMF/DSHOW) seja a mesma ordem em que o WMI devolve os dispositivos PnP.

O guard que existe compara apenas **contagens**:

```python
if len(names) != len(working):
    names = []
```

Ele cobre o caso de dispositivo a mais/a menos (foi escrito para o problema dos scanners de rede entrando pela classe `Image`, ver `../d-specs/webcam-ugreen-4k.md`), mas **não cobre contagens iguais com ordem trocada** — que é exatamente o que aconteceu: 2 câmeras de cada lado, ordens opostas, guard satisfeito, rótulos invertidos.

O próprio docstring da função enuncia o princípio que a implementação viola:

> showing a wrong name next to an index is worse than no name

Ou seja: não é uma decisão de design que envelheceu, é um caso não coberto de uma regra que o próprio código declara querer seguir.

## Como evitar / mitigar
- **Enquanto não corrigido**: não confiar no nome mostrado por `--list-cameras`. Confirmar qual índice é qual capturando um frame de cada (`--source camera --camera-source N`) e olhando a imagem.
- A correção já está enfileirada como tarefa própria — esta P-spec registra o problema conhecido, não a solução. A direção geral é casar índice e nome por identidade de dispositivo em vez de por posição, ou (seguindo o princípio do próprio docstring) descartar os nomes sempre que a correspondência não puder ser afirmada, não só quando as contagens divergem.

## Status
Aberto — 2026-08-14. Observado com consequência real (câmera errada aberta durante uma medição); correção enfileirada, ainda não aplicada.
