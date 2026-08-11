# A suíte de testes nunca foi executável a partir de um clone limpo

## O problema
`test_selection.py` quebra com `FileNotFoundError` na terceira fixture real, em qualquer clone do repositório:

```
test_selection.py:53   "captures/20260803-154414_auto": {"ACPI": "menu_column"}
study_selection_methods.py:45  "captures/20260803-154414_auto": "ACPI"
```

O par `captures/20260803-154414_auto.png` / `.json` **nunca esteve no git** — `git log --all -- 'captures/20260803-154414*'` volta vazio. Não é arquivo apagado nem ignorado por engano: nunca foi commitado. Até onde foi observado, a suíte só rodou até o fim em máquinas onde o arquivo existia localmente.

Antes de bater nesse erro a suíte passa: sintéticos 3/3 OK, AMI reais 2/2 OK. Ou seja, o sinal de "está tudo bem" chega antes do erro, o que ajuda o problema a passar despercebido.

Descoberta em 2026-08-07 ao rodar a suíte durante outra tarefa. É anterior a essa sessão e independe dela.

## Onde ele mora
- `test_selection.py:53` — gabarito de seleção.
- `study_selection_methods.py:45` — mesma fixture, no script do estudo `../../studies/ESTUDO_SELECAO.md`, que portanto também não é reproduzível na íntegra.
- `.gitignore` — a regra `captures/*` com exceções nomeadas (`!captures/20260803-1543*`) *cobriria* esse arquivo; a exceção existe. Só o arquivo é que não.

## Por que existe
Fixture criada localmente e referenciada em código antes de ser adicionada ao repositório. A regra de `.gitignore` que existe para isso (`!captures/20260803-1543*`) casaria com o nome — o que torna a ausência mais fácil de não notar, porque nada no `.gitignore` aponta para a lacuna.

O padrão se repetiu depois, com outras evidências: os frames `captures/*_bench_live.png` do estudo de motores de OCR e a fixture `captures/20260806-144020_auto.png` também são citados por docs e nunca foram commitados (`git log --all` vazio para os três caminhos). Ou seja, a causa estrutural é **evidência citada por código/doc sem passo que garanta que ela entrou no repositório**, não um esquecimento isolado.

## Caso mais grave da mesma família: a varredura de ~240 negativas não existe mais (2026-08-10)

Descoberto ao montar a validação de acurácia dos motores de OCR (`../../studies/estudo-motores-ocr.md`). O corpus de **~240 capturas sem seleção nenhuma**, usado historicamente para medir taxa de falso positivo, **foi embora**: eram dados de sessão, nunca versionados. Do gabarito negativo sobrou **1 imagem** (`test_bios_noselect.png`, sintética).

Isso é pior que uma fixture faltando, porque o número que aquele corpus produzia continua citado como se ainda fosse verificável, em quatro lugares:

| Onde | O que afirma |
|---|---|
| `test_selection.py:63-64, 252` | 1,4% → 2,0%+ de falso positivo na varredura de ~240; usado como justificativa para **não** baixar um limiar |
| `../../architecture/VISUAL_FEATURE_SPEC.md:533` | "~240 capturas sem seleção — mede falso positivo, já em uso" |
| `../../reference/PROCESSO_OCR.md:77` | 2,0% de falsos positivos (39,5% na primeira versão; 1,4% antes do menu vertical) |
| `../../studies/ESTUDO_SELECAO.md:21, 112, 140` | mesma varredura, as três taxas |

Consequências concretas:
- **Um argumento de projeto ficou sem base verificável.** O comentário de `test_selection.py:63` rejeita admitir um valor mais baixo porque isso "empurraria a varredura de 1,4% para 2,0%+" — não há mais como reproduzir essa medição, nem para confirmá-la nem para revisá-la.
- **Qualquer taxa de falso positivo medida hoje não é comparável com o histórico.** A validação de 2026-08-10 reporta 0 falsos positivos para o rapidocr; isso vale sobre 1 negativo verdadeiro mais 10 positivos, não sobre 240 imagens. Números com ordens de grandeza de diferença em tamanho de amostra não pertencem à mesma escala e não devem ser lidos lado a lado.

Nenhum dos quatro documentos acima foi alterado para apagar as taxas históricas: elas são registro do que foi medido na época e continuam válidas como tal. O que faltava era dizer em algum lugar que **não são mais reproduzíveis** — é o que esta seção faz.

## Como evitar / mitigar
Não corrigido — a fixture continua ausente e a suíte continua quebrando nela.

Opções, nenhuma aplicada:
- **Recriar/recapturar** `20260803-154414_auto` e commitá-la (só possível se a tela original for reproduzível).
- **Remover a entrada** do gabarito em `test_selection.py` e de `study_selection_methods.py`, deixando a suíte verde e honesta sobre o que cobre.
- **Falhar explicitamente**: fixture ausente vira `skip` com mensagem, não `FileNotFoundError` no meio da execução.

Verificação barata que fecha a família inteira do problema: para cada caminho de `captures/` citado em código ou em `docs/`, conferir `git log --all -- <caminho>`.

**Caso vivo, ainda recuperável (2026-08-10)**: os dois frames que sustentam a validação da regra de classe fina no E7 e o diagnóstico do canal de borda ausente — `captures/20260810-153639_bench_live.png` e `captures/20260810-153155_bench_live.png` — **existem em disco** e estão cobertos pela exceção `!captures/*_bench_live.png` do `.gitignore`, mas continuam **não commitados** (`git status` os mostra como untracked). É exatamente a situação em que os frames de 2026-08-07 se perderam. Commitá-los é a ação barata que evita repetir a perda; docs que dependem deles: `classe-fina-canal-unico-eleito-por-ruido.md` e `campo-focado-por-borda-sem-canal-no-e7.md`.

Para o corpus de ~240 negativas não há recuperação — as imagens não existem mais em lugar nenhum. As opções são recapturar um corpus negativo novo (que não seria comparável com o histórico, e isso teria que ficar dito) ou aceitar que a métrica de falso positivo do projeto passa a ser medida em amostra pequena, com a fraqueza declarada em cada uso.

**Regra prática que este caso sugere**: número que sustenta decisão de projeto precisa ou de evidência versionada, ou de um aviso explícito de que não é reproduzível. Sem isso, ele envelhece parecendo verificável.

## Status
Aberto — 2026-08-07, agravado em 2026-08-10 (perda do corpus de ~240 negativas). Diagnosticado, não corrigido. A fixture AMI `20260803-154414` continua ausente e por isso só 2 das 3 entraram na validação de acurácia dos motores de OCR.
