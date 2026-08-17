# Votação de OCR não protege a detecção quando o frame representante é o ruim

## O problema
A corroboração por votação multi-frame (`../f-specs/corroboracao-ocr-multi-frame.md`) só reduz ruído no *conteúdo* de caixas de texto já detectadas — ela não protege a *detecção* em si. Se o frame usado para detectar onde as caixas estão for ele mesmo o frame degradado (desfocado, com glare bem naquele instante), a votação não recupera nada, porque a detecção já falhou antes de a votação entrar em cena.

Testado deliberadamente em 2026-08-14 sobre a captura real de 48 primitivos (`captures/20260812-160027_auto.png`) mais uma variante borrada da mesma imagem:
- `frames=[img_bom, img_bom, img_borrado]` — o último frame (`img_borrado`) é o representante (`FrameBundle.representative == frames[-1]`). Detecção caiu de 48 primitivos para 2.
- `frames=[img_borrado, img_bom, img_bom]` — o frame ruim é um dos extras, não o representante. Resultado idêntico ao de rodar com um frame só (0 mudanças) — confirma que um frame degradado *entre os extras* não corrompe nada, porque extras só entram na votação de conteúdo, nunca na detecção.

A conclusão prática: a qualidade da leitura inteira, com `ocr_votes` qualquer, ainda depende inteiramente de um único frame — o último do burst — não do conjunto.

## Onde ele mora
`perception/stages/e2_extraction.py`, `SymbolicSource.extract`: a leitura primária (que decide geometria de todas as caixas) sempre roda sobre `surface.image`, que por sua vez é derivada de `bundle.frames[-1]` (E1 passa o representante adiante em identity pass-through). A corroboração (`_corroborate`) só toca os frames restantes do bundle, e só para revotar texto dentro de caixas que a leitura primária já fixou. Afeta `../f-specs/corroboracao-ocr-multi-frame.md` diretamente, e por extensão qualquer captura ao vivo com burst instável — a mesma classe de ruído documentada em `glare-moire-degradam-ocr-captura-ao-vivo.md`.

## Por que existe
É uma consequência direta da decisão de arquitetura da própria feature: ter uma única passada de detecção evita o problema difícil de casar caixas detectadas independentemente entre execuções diferentes (número de caixas pode divergir entre leituras). Escolher "o último frame do burst" como representante é uma regra simples de E0 (Aquisição) — "o mais recente de uma observação estável" — que não considera nitidez/qualidade por frame, só estabilidade temporal. Nenhuma etapa hoje escolhe o representante por qualidade de imagem.

## Como evitar / mitigar
Não corrigido. Direção óbvia e não implementada: escolher como representante o frame mais nítido do burst (por alguma métrica de foco/nitidez), em vez de simplesmente "o último" — mas isso é mudança de comportamento de E0/E1, fora do escopo do que foi entregue nesta sessão, e não foi medida. Até lá, o sistema não reage de forma alguma a essa condição — não há abstenção nem aviso quando o representante é ruim; ele é lido normalmente e a detecção degrada silenciosamente, sem que a votação (nem nenhum outro estágio) perceba. Isso é uma lacuna real frente ao princípio de abstenção-antes-de-chute (`../../architecture/PERCEPTION_PIPELINE_SPEC.md` §2) — vale considerar no futuro se E0/E1 deveriam medir nitidez do representante e registrar isso como parte da proveniência (F4), mesmo sem trocar o algoritmo de escolha.

## Status
Aberto — 2026-08-14. Encontrado e confirmado por teste deliberado durante a implementação da votação multi-frame; nenhuma correção aplicada.
