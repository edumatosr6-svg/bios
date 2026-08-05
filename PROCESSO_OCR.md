# Processo de OCR — referência

Pipeline fechado em 2026-08-03. Cobre da captura da câmera até a saída final; não inclui a arquitetura de múltiplas câmeras/múltiplos modelos de BIOS (deliberadamente deixada de fora por enquanto).

## Etapas

1. **Captura contínua**
   Uma câmera (física ou stream de rede) fica sendo lida continuamente. Nenhum humano tira foto — o software olha o feed o tempo todo.

2. **Detecção automática de tela estável**
   O sistema compara frames consecutivos (diferença média de pixel). Quando a imagem para de mudar por N frames seguidos, considera que a tela "assentou" (ex: o menu da BIOS carregou por completo, não está mais em transição/animação). Um debounce evita reprocessar a mesma tela parada repetidamente.

3. **OCR (PaddleOCR)**
   Na tela estável, roda OCR e gera um JSON estruturado: texto completo + por palavra/linha/bloco, com bounding box e confiança. Esse é o `raw_ocr` — a fonte da verdade, nunca alterado depois.

4. **Detecção de item selecionado/destacado**
   O OCR sozinho não vê qual item está selecionado — só lê caracteres. `selection.py` analisa as cores do frame original dentro das bounding boxes que o OCR já calculou.

   BIOS marca seleção de **duas formas diferentes**, e as duas são detectadas:
   - **Sinal A — barra de fundo invertida**: um bloco sólido de cor contrastante atrás do item (ex: barra branca com texto preto numa tela preta).
   - **Sinal B — cor de texto diferente**: o fundo não muda, só a cor do texto do item selecionado (é assim que a BIOS AMI real das nossas fotos funciona: o item selecionado fica branco enquanto os outros ficam azuis).

   E o menu pode ser **horizontal ou vertical**: a BIOS AMI usa uma barra de abas no topo, a BIOS Positivo (2º modelo real testado) usa uma coluna lateral à esquerda. As linhas são agrupadas tanto em fileiras quanto em colunas (por posição na tela), e cada grupo grande o bastante (`region: "menu_strip"` pra fileira, `region: "menu_column"` pra coluna) é julgado contra si mesmo, não contra a tela toda — necessário porque menu e corpo costumam ter cores de fundo bem diferentes. `region: "body"` sobrou pra itens isolados que não fazem parte de nenhuma lista grande.

   Isso também permite **múltiplos níveis de seleção ao mesmo tempo**: a aba/item ativo no menu (`menu_strip`/`menu_column`) e o item focado no corpo — cada linha destacada carrega essa informação, e os níveis podem aparecer juntos na mesma tela (visto de verdade numa foto real: aba "Advanced" ativa + item "ACPI Configuration" focado, ao mesmo tempo).

   Roda sempre (é só processamento de imagem, sem chamada de rede). Ver "Precisão da detecção" abaixo para como isso foi calibrado, e `ESTUDO_SELECAO.md` para o comparativo de métodos, a validação contra 2 modelos de BIOS reais, e as limitações conhecidas que restaram.

5. **Extração de campos via LLM local**
   O texto bruto do OCR vai pro modelo Qwen3 4B rodando na NPU da máquina da fábrica (Lemonade/FastFlowLM). Ele organiza o texto em pares `"BIOS Version": "F.31"`, etc., e pode limpar rótulos conhecidos com erro de OCR (ex: "Systym Date" → "System Date"). Ele **nunca** deve alterar o valor em si.

6. **Verificação de segurança**
   Cada valor que o LLM devolve é conferido: precisa aparecer literalmente no texto que o OCR leu. Se não bater, esse campo vai pra uma lista separada (`fields_unverified`) em vez de ser confiado. Isso já pegou o LLM errando um valor na prática (ver "Incidente real" abaixo).

7. **Saída**
   O resultado final tem os dois formatos, lado a lado:
   - `raw_ocr`: bruto, pra auditoria/rastreabilidade
   - `fields` / `fields_unverified`: já extraídos e verificados, pra uso prático

   Hoje isso é gravado como JSON local (`captures/`). Não construímos um destino mais elaborado (banco, dashboard) porque o consumidor real dessa saída é a futura fase de IA que vai operar a BIOS — essa fase ainda não existe, então qualquer destino mais sofisticado agora seria over-engineering.

Cada etapa pesada (OCR e chamada do LLM) roda isolada em processo separado (`multiprocessing`, não thread) — a GIL do Python fica presa por segundos durante essas chamadas, e isso já causou a janela travar ("Não está respondendo") quando rodava numa thread. Em processo separado, a interface nunca trava, não importa quanto tempo a etapa demore.

## Incidente real (por que a verificação existe)

Em teste com o texto sintético de BIOS, o LLM recebeu instrução explícita de nunca alterar valores, mas mesmo assim devolveu:

```
"System Date": "Thu 07/30/20026"
```

O valor real lido pelo OCR era `07/30/2026` — o modelo inseriu um dígito extra sozinho. A verificação mecânica (etapa 6) pegou esse erro automaticamente e moveu o campo pra `fields_unverified` em vez de deixá-lo passar como dado confiável.

**Conclusão prática:** nunca confiar em `fields` sem a etapa de verificação. Não é uma proteção opcional.

## Precisão da detecção de seleção (etapa 4)

A primeira versão marcava **39,5% de todas as linhas** como selecionadas — inutilizável. Três erros, corrigidos:

1. **Estimava o fundo como "cor mais comum do recorte".** Como o bbox do OCR é justo no texto (medimos 51–73% dos pixels sendo letra), a cor mais comum era a **cor da letra**, não do fundo. Corrigido amostrando o fundo pela **borda** do bbox (as letras ficam no miolo), usando mediana.

2. **Só procurava barra de fundo invertida.** A BIOS AMI real das nossas fotos marca seleção pela **cor do texto**, com o fundo inalterado — o detector não só perdia o item certo ("ACPI Configuration") como marcava o errado ("Main"). Corrigido adicionando o sinal B.

3. **Comparava com um limiar fixo.** Agora o sinal B compara a cor do texto de cada linha com a **mediana das outras linhas da mesma tela**, e exige que se destaque em relação à dispersão delas (MAD). Isso se adapta sozinho à paleta de cada BIOS — importante porque os 3 modelos-alvo devem ter esquemas de cor diferentes — e separa "item selecionado" de "tela só colorida": nas fotos reais o item selecionado fica a 236–267 da mediana enquanto todos os outros ficam entre 3 e 43.

Além disso, o sinal B é limitado a **um item por tela**: uma BIOS seleciona exatamente um item, então várias linhas com cor estranha significam que aquela tela não está mostrando seleção nenhuma.

Resultado, medido por `test_selection.py` (2026-08-04, após validar contra o 2º modelo de BIOS real — Positivo, menu vertical):

| Conjunto | Resultado |
|---|---|
| Sintéticos (barra invertida, gabarito por construção) | 3/3 exatos |
| Fotos de BIOS AMI real (menu horizontal) | 3/3 exatos |
| Fotos de BIOS Positivo real (menu vertical) | 4/5 barra lateral, 1/4 item de submenu (limitações documentadas em `ESTUDO_SELECAO.md`) |
| ~240 capturas sem seleção nenhuma | 2,0% falsos positivos (era 39,5% na primeira versão; 1,4% antes de generalizar pra menu vertical) |

Duas limitações conhecidas e não resolvidas às cegas, ambas documentadas com o número exato medido em `selection.py` e `ESTUDO_SELECAO.md`: (1) uma foto com sinal de cor mais fraco que o piso calibrado (ângulo/exposição variam de foto pra foto); (2) itens de submenu com uma linha de descrição colada embaixo, onde o vazamento de cor da barra de destaque na foto real deixa a descrição quase tão "suspeita" quanto o item de verdade.

Rodar após qualquer mudança:

```bash
py -3.13 test_selection.py
```

## Peças de código

| Arquivo | Papel |
|---|---|
| `capture.py` | Captura de câmera (índice ou URL), listagem de dispositivos |
| `ocr.py` | Motores de OCR (Tesseract, PaddleOCR) atrás de uma interface comum |
| `selection.py` | Detecção de item destacado/selecionado por análise de cor |
| `test_selection.py` | Mede a precisão da detecção de seleção contra gabarito |
| `make_test_image.py` | Gera as telas de BIOS sintéticas de teste |
| `study_selection_methods.py` | Compara 4 métodos de detecção (ver `ESTUDO_SELECAO.md`) |
| `study_temporal.py` | Estuda detecção por movimento entre frames |
| `extract.py` | Chamada ao LLM local + verificação de valores |
| `watcher.py` | Loop automático headless (linha de comando) |
| `gui.py` | Interface gráfica de teste local (vídeo + resultado lado a lado) |
| `main.py` | CLI de teste pontual (uma captura só, arquivo ou câmera) |
| `sender.py` | Grava o resultado final (JSON + PNG) em `captures/` |

## Como testar o pipeline completo

```bash
py -3.13 main.py --source file --input test_bios.png --engine paddleocr --extract-fields --output resultado.json
```

Requer o túnel SSH pro Lemonade Server ativo (`ssh -L 13305:127.0.0.1:13305 bios@192.168.0.52`) pra `--extract-fields` funcionar; sem o túnel, o pipeline continua funcionando só com `raw_ocr` (a extração falha de forma tratada, sem derrubar a captura).
