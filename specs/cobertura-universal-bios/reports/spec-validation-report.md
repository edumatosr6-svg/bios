# Spec Validation Report — cobertura-universal-bios

**Iteração: 2**
**Veredito: SUCCESS**

## Pontos verificados
- [x] Completude — F0–F5 cobrem tudo de `descriptions.md`; todo CA é verificável
- [x] KPIs — K1–K14 mensuráveis, rastreados a feature, com gate de medição explícito
- [x] Testabilidade — 7 arquivos em `tests/`, caminho feliz + bordas + falhas por feature
- [x] Consistência interna — as três contradições da iteração 1 foram resolvidas
- [x] Consistência entre slugs (contratos externos)
- [x] Consistência com implementation-report — não existe (nenhuma tentativa de impl ainda)
- [x] Consistência com references/ — `references/` vazia; nada a violar
- [x] Tools — cobre o necessário, sem dependência nova especulativa

## Contratos entre slugs

`cobertura-universal-bios` continua sendo o **único** slug em `specs/`. Nenhum
contrato atravessa fronteira de slug nesta rodada — nada a verificar, nada quebrado.

Registrado para o futuro slug das tools nomeadas (fora de escopo aqui): ele vai
consumir (a) o esquema de `data/label_index.json`, agora com a seção `pages`
(`page_id`, `total_screens`, `signatures`) além de `entries`; e (b) a semântica de
três desfechos do `ToolResult` de `find_setting`, onde `ok=True` + `value=None`
significa "não existe nesta BIOS" e é **diferente** de `ok=False`. Esse segundo é o
caso perigoso de "mesma forma, significado diferente" e deve ser reverificado quando
aquele slug for escrito.

## Resolução dos problemas da iteração 1

| # | Problema | Como foi resolvido | Status |
|---|---|---|---|
| P1 | `LabelEntry` sem `total_screens`/assinatura, tornando P2 inexecutável a partir do disco | Nova seção `pages` no índice (CA-F3.2a) com `total_screens` e `signatures` por `screen_index`; P2 reescrito recebendo o `PageRecord`; validação de integridade referencial em CA-F3.9; casos CT-F3.2a–d e CT-F4.2a | Resolvido |
| P2 | Bootstrap circular das grafias de submenu, K6 inatingível | Nova feature **F0** + procedure P3a: colheita crua sem casamento, revisão humana explícita de `labels.py`, CA-F0.5/K12 exigindo evidência para todo CONFIRMADO, K13 exigindo os 8 declarados; ordem F0→F3 obrigatória | Resolvido |
| P3 | `provenance: "palpite"` ambíguo | CA-F2.1a define o comportamento por caminho numa tabela de 4 linhas (F2 direta / F3 / F4 / K6), e CT-F2.12 virou quatro casos independentes | Resolvido |
| P4 | K3 malformado e redundante | K3 reescrito como **qualidade** da abstenção (escopo presente em 100% dos `notes`), que pode falhar independentemente de K1/K2; CT-K3 correspondente | Resolvido |
| P5 | `question-bank.md` exigido mas sem dono | Nova feature **F5** com CA-F5.1–F5.6, marcando a entrada humana como bloqueante, CA-F5.5 fazendo o runner recusar medir banco incompleto, novo K14 e casos CT-K14/CT-K0 | Resolvido |
| P6 | Quem classifica intenção de escrita/precedência | CA-F4.1a divide explicitamente: assistente escolhe a tool e extrai `term`; a guarda de escrita é **redundante na tool**, por design; assinatura passou a `term` + `question` opcional; CT-F4.14a–c e CT-F4.17–17b | Resolvido |

Nenhum problema é **recorrente**.

## Observações

### Débitos aceitos conscientemente

1. **Página truncada distorce o `total_screens` do índice.** CA-F1.7 permite parar em
   `max_screens=12` marcando truncamento. Se uma página real tiver mais de 12
   screenful, o `PageRecord` gravará `total_screens=12`, e o passo 1 de P2 (`pageup` ×
   14) pode não alcançar o topo — o reposicionamento cairia no lugar errado.
   **Por que não é bloqueante:** o passo 4 de P2 compara assinaturas e falha com
   `INDICE_DESATUALIZADO` antes de ler qualquer coisa. A consequência é perda de
   cobertura (K2), nunca resposta errada (K1) — que é a propriedade que o slug
   protege. Recomendação para a implementação: excluir páginas truncadas do índice ou
   marcá-las, e tratar isso como `FAIL SPEC` se aparecer em hardware real.

2. **CA-F4.7 usa fraseado herdado** ("usa F2 quando a entrada tem `submenu`"), de
   quando `submenu` vivia em `LabelEntry`. O campo agora vive em `PageRecord`, e P5
   passo 4 e os Data Models descrevem o acesso correto (`pages[entry.page].submenu`).
   Não é ambiguidade implementável — `LabelEntry.submenu` simplesmente não existe, então
   a leitura errada é impossível de codificar — mas convém corrigir o texto no primeiro
   contato.

3. **K6 (≥ 8 submenus) é uma aposta empírica.** Depende de os oito submenus de
   `descriptions.md` realmente existirem e serem visíveis nesta máquina. Se o hardware
   revelar menos, o número certo é ajustar K6 com a evidência de `data/raw_labels/`,
   não relaxar a disciplina de provenance.

4. **Limiar de 70% em P2** e **`max_screens=12`** são valores escolhidos, não medidos.
   Ambos falham de forma segura (para a leitura em vez de adivinhar) e são
   justificados no texto. Aceitos.

### Riscos fora do controle da spec

- **K1–K4 não são declaráveis pelo impl-loop sozinho**: exigem a máquina alvo e as ≥ 10
  perguntas não ensaiadas escritas por humano (CA-F5.3). O gate de F5 e o bloco
  separado em `tests/kpis.md` deixam isso explícito, de modo que o loop feche
  legitimamente com K5–K14 verdes e reporte K1–K4 como `NAO MEDIDO` em vez de um
  número otimista. Isso é intencional, não uma lacuna.
- A edição de `biostools/labels.py` é ato humano por design (CA-F0.3). Se o impl-loop
  automatizá-la, a disciplina de provenance do projeto é anulada — vale vigiar na
  validação de código.

**Pronto para o impl-loop.**
