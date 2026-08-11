# Lentidão do PaddleOCR em CPU sem mkldnn

## O problema
Construir `PaddleOCREngine` (`ocr.py`) com a configuração herdada do commit inicial — `enable_mkldnn=False`, sem `ocr_version` explícito — leva mais de 7 minutos de CPU contínua sem sequer terminar. Medido nesta sessão (2026-08-07, Windows, 12 núcleos, sem GPU — `paddle.device.is_compiled_with_cuda()` retorna `False`): 7-9 dos 12 núcleos ocupados o tempo todo, processo morto manualmente após 7min14s sem que a construção do engine (nem uma primeira chamada a `predict()`) tivesse terminado. Isso torna tanto o motor de percepção (`perception/`) quanto o caminho legado (`main.py` + `selection.py`) inutilizáveis em uso interativo — foi o sintoma relatado ("motor perception muito lento na leitura/OCR") que motivou esta investigação.

## Onde ele mora
`ocr.py`, classe `PaddleOCREngine` — alcançável pelos dois caminhos do projeto: o legado (`main.py`/`watcher.py`, ver `../../reference/PROCESSO_OCR.md`) e o motor novo (`perception/stages/e2_extraction.py`, fonte simbólica de primitivas — ver `../f-specs/motor-percepcao-interface.md`).

**Alcance atualizado (2026-08-10):** quando este teto foi registrado, PaddleOCR era o default e portanto *todo* caminho que rodasse OCR passava por aqui. Desde 2026-08-07 o default é `rapidocr-openvino` (`ocr.py::DEFAULT_ENGINE`), em CLI e em biblioteca — quem roda o default **não paga mais este teto**. Ele hoje só é pago por quem passa `--engine paddleocr` explicitamente. O teto não deixou de existir; deixou de estar no caminho padrão.

## Por que existe
Duas causas medidas nesta sessão, a segunda só relevante por causa da primeira:

1. **Bug do PaddlePaddle 3.3.1 (oneDNN/PIR), não corrigido upstream.** Reabilitar `enable_mkldnn=True` derruba a construção do engine para ~21-24s — mas a primeira chamada a `predict()` crasha em menos de 0.1s com `ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]`. Testado com dois pares de modelo (PP-OCRv6 "medium" e PP-OCRv4 "mobile"): o crash é idêntico e imediato nos dois, ou seja, é um bug da versão do framework, não peculiaridade de um modelo. `pip index versions paddlepaddle` confirma que 3.3.1 já é a versão mais recente disponível no momento da medição — não há upgrade para testar se corrige.
2. **Sem mkldnn, o executor CPU do Paddle escala muito mal com o tamanho do grafo do modelo.** `enable_mkldnn=False` (obrigatório por causa do item 1) força um caminho de execução cujo custo de construção explode conforme o modelo cresce. `PaddleOCR(lang="en", ...)` sem `ocr_version` explícito escolhe por padrão o par PP-OCRv6 "medium" (det+rec) — foi exatamente essa combinação (mkldnn desligado + modelo médio implícito) que produziu os 7min+ sem terminar.

Ver `../d-specs/paddleocr.md` para a ferramenta em si (por que PaddleOCR foi escolhido, como é configurado hoje).

## Como evitar / mitigar
Não há correção disponível — só contorno, e o contorno reduz o custo, não o elimina. `ocr.py::PaddleOCREngine` fixa `ocr_version="PP-OCRv4"` (par "mobile", bem menor) em vez de aceitar o default implícito do PaddleOCR; com isso, construção cai para ~2.4-9.4s (cache quente vs. frio) e uma leitura completa numa captura real 1280x720 fica em ~30-31s — ver `../d-specs/paddleocr.md` para a medição completa e o trade-off que essa repinagem introduz. `enable_mkldnn` continua `False`: religá-lo não é uma opção enquanto o bug de PIR persistir em 3.3.1 — confirmado por teste direto nesta sessão, não é mais só uma suposição herdada do comentário original.

Qualquer modelo maior que o par "mobile" atual (upgrade de acurácia, outro idioma, etc.) reabre este teto — o custo de construção sem mkldnn escala com o tamanho do modelo, não é uma constante fixa que a repinagem atual "resolveu" de vez.

Revisitar quando: uma versão futura do PaddlePaddle corrigir o crash de oneDNN/PIR (nenhuma disponível hoje). Nesse caso `enable_mkldnn=True` volta a ser viável e a escolha de `ocr_version` pode ser reaberta com mkldnn no caminho rápido, não no caminho lento atual.

**Atualização na mesma sessão — o teto se provou incontornável dentro do PaddlePaddle para a meta do projeto.** Depois da repinagem, a meta ficou explícita: <8s por leitura. O PaddleOCR repinado continua em 37-44s de leitura (fixture e frame ao vivo — medições em `../../studies/estudo-motores-ocr.md`), e os dois caminhos de aceleração dentro do ecossistema foram fechados nesta máquina (sem GPU NVIDIA, i5-1235U com Iris Xe integrada):

- **paddlex HPI (backends openvino/onnxruntime do próprio ecossistema)**: `paddlex --install hpi-cpu` falha em Windows nativo com `No matching distribution found for ultra-infer-python` — não há wheel Windows, e a doc do PaddleX manda usar WSL/Docker. O usuário decidiu explicitamente não ir para WSL por ora.
- **DirectML na Iris Xe**: não tentado — bugs conhecidos de inferência incorreta nessa iGPU.

A mitigação efetiva foi **sair do runtime PaddlePaddle mantendo a linhagem de modelos**: `RapidOCREngine` (`ocr.py`), rodando PP-OCR via ONNX com backend OpenVINO, atinge **4.53s de leitura quente ao vivo** — ver `../d-specs/rapidocr.md` e `../f-specs/selecao-motor-ocr.md`. Ainda em 2026-08-07 essa mitigação passou a valer por omissão: `rapidocr-openvino` virou `DEFAULT_ENGINE`, então o caminho padrão do projeto não passa mais por este teto. A validação formal de acurácia **não precedeu** essa troca, mas foi feita em 2026-08-10 e a confirmou (`../../studies/estudo-motores-ocr.md`): sair do runtime PaddlePaddle para escapar deste teto **não custou acurácia de leitura**.

## Status
Mitigado — 2026-08-07, alcance revisado em 2026-08-10. O bug de oneDNN/PIR no PaddlePaddle 3.3.1 continua sem correção upstream, e ficou demonstrado que a meta de <8s é inalcançável dentro do PaddlePaddle nesta máquina (repinagem de modelo insuficiente, HPI sem wheel Windows, WSL descartado). Mitigação real e já em vigor por omissão: `rapidocr-openvino` como `DEFAULT_ENGINE`, fora do runtime Paddle. O teto permanece intacto **dentro do `PaddleOCREngine`** — quem pedir `--engine paddleocr` continua pagando 37-44s por leitura —, mas saiu do caminho padrão do projeto.
