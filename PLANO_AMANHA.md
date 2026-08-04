# Plano — 2026-07-31

## Contexto
Prototipo em `C:\dev\bios` já testado hoje (2026-07-30): captura de câmera + OCR (Tesseract) + detecção automática de tela estável + GUI desktop (câmera + texto lado a lado). Fluxo automático fim-a-fim confirmado funcionando no PC de teste (Windows). Pendências abaixo.

## 1. Resolver a câmera (bloqueio de agora)
- A Brio 500 caiu para status "Unknown" no Windows depois de vários testes de abrir/fechar o processo abruptamente.
- **Ação**: desconectar e reconectar o cabo USB da câmera fisicamente, depois reabrir `gui.py` para confirmar que volta a funcionar.

## 2. Testar a GUI (`gui.py`)
- Rodar `python gui.py --camera-index 0` e validar visualmente: vídeo ao vivo de um lado, texto do OCR do outro, atualizando automaticamente quando a tela observada estabiliza.
- Testar o botão "OCR now" (disparo manual, útil para debug).
- Ajustar `--stable-threshold` / `--stable-frames` / `--change-threshold` observando o comportamento real (esses valores ainda são só estimativas, não calibrados).

## 3. Testar contra uma tela de BIOS real
- Até agora só testamos apontando a câmera pro monitor do próprio PC (chat/terminal), não uma BIOS de verdade.
- Se houver acesso a alguma máquina que possa reiniciar e entrar na BIOS: apontar a câmera pra ela e validar a leitura real (nomes de campos, versão, etc.) — inclusive testando distância/ângulo da câmera, já que hoje vimos que câmera longe/em ângulo faz o OCR não ler nada.

## 4. Preparar o deploy na máquina da fábrica (`bios-ai-srv-0004`)
- Levar o código (`capture.py`, `ocr.py`, `sender.py`, `watcher.py`, `gui.py`) para a máquina Linux via SSH.
- Confirmar lá: Tesseract instalado (`apt install tesseract-ocr`), câmera USB reconhecida (`v4l2-ctl --list-devices` ou similar), Tkinter disponível se for usar a GUI lá (ou decidir se a interface roda no Windows olhando a câmera remota via rede).
- Validar que o fluxo automático (watcher/gui) funciona igual no Linux — atenção: os "gotchas" de câmera vistos hoje (travamento ao matar processo, cold-start lento) são específicos do driver MSMF do Windows e podem não se repetir no Linux (usa V4L2), mas precisa reconfirmar lá.

## 5. Decisões ainda em aberto
- **Destino dos dados**: `sender.py` hoje só grava JSON+PNG em `captures/` local. Definir se vai virar banco de dados, dashboard, webhook, ou envio direto pro endpoint da IA (Lemonade/FastFlowLM).
- **Engine de OCR**: usando Tesseract por ser mais simples de instalar; considerar PaddleOCR depois se a precisão em layouts de BIOS reais não for suficiente.
- **Acesso às 3 máquinas com BIOS diferentes**: ainda não disponível — necessário para calibrar o pipeline com casos reais e, futuramente, treinar/testar a IA de identificação de modelo/versão.

## Resumo rápido
| Item | Status |
|---|---|
| Captura de câmera automática | ✅ funcionando (Windows) |
| Detecção automática de tela estável | ✅ funcionando |
| OCR com coordenadas (JSON) | ✅ funcionando |
| GUI desktop (vídeo + texto) | 🔧 criada hoje, câmera travou antes de testar — testar amanhã |
| Teste com BIOS real | ⏳ pendente |
| Deploy na máquina da fábrica | ⏳ pendente |
| Definição do destino dos dados | ⏳ pendente |
