# Tooling — cobertura-universal-bios

## Test runner

O projeto já tem sua suíte em `test_biostools.py`, executada como script:

    py -3.13 test_biostools.py

**Este é o "Tester TOOL" do impl-loop.** Não introduzir pytest, tox ou outro runner
neste slug — o padrão existente (script único, `FakeBios` servindo contratos de
percepção reais a partir de fixtures em `captures/`, contratos cacheados para não
pagar OCR por execução) é exatamente o que os testes deste slug precisam, e trocá-lo
sairia do escopo.

Os novos casos de `tests/` entram nesse arquivo (ou em módulos irmãos importados por
ele), seguindo o padrão existente:
- rodam com câmera e cabo ausentes;
- usam uma sessão fake que registra teclas em `pressed`;
- fixtures de rolagem (multi-screenful) precisam ser **commitadas** junto — a mesma
  regra do índice.

## Marcação de testes de bancada

Casos marcados `[BANCADA]` em `tests/` exigem hardware e **não** rodam na suíte
padrão. Devem ficar atrás de uma flag explícita (ex.: `--bench` /
`BIOSTOOLS_BENCH=1`) e serem pulados com mensagem clara quando ausente — nunca
falhar por falta de hardware, e nunca rodar por acidente contra uma máquina real.

## Validador de esquema do índice

Um verificador puro (sem hardware) para `data/label_index.json`, chamável de duas
formas:
- como caso da suíte (`CT-F3.2`–`CT-F3.5`);
- como comando (`py -3.13 -m biostools validate-index`), para uso do operador antes
  da demo.

Deve falhar nomeando a entrada ofensora, não só devolver "inválido".

## Checagem de versionamento

Uma checagem executável (na suíte ou em script) que confirma:
- `git ls-files data/label_index.json` retorna o caminho;
- nenhuma regra de `.gitignore` cobre `data/label_index.json` nem as fixtures novas.

Existe porque o projeto já perdeu um corpus por isso
(`docs/specs/p-specs/fixture-de-teste-nunca-versionada.md`) e a demo depende do índice.

## Validador do banco de perguntas

Verificador puro de `question-bank.md` (contagens de CA-F5.1–F5.4 e formato de cada
linha). É o que faz o runner de KPIs recusar medir K1–K4 sobre banco incompleto
(CA-F5.5) em vez de reportar um número enganoso.

## Estudos de bancada

Novo: `study_label_index.py` na raiz, junto de `study_scroll_map.py` e
`study_menu_tour.py`, com `argparse` e as mesmas flags (`--serial-port`, `--engine`),
mais dois modos:
- `--harvest` — colheita crua de F0 (P3a), antes de haver grafias declaradas;
- (padrão) — tour de índice de F3 (P4), depois da revisão humana de `labels.py`.

Estudos são scripts operados por humano, não parte da suíte automática.

## CLI

`biostools/__main__.py` ganha os subcomandos `find-setting --term ... [--question
...]`, `validate-index` e `validate-question-bank`, no mesmo formato estruturado de
saída das tools existentes — sem segundo formato de output.

## Lint / formatter / CI

O projeto não tem lint nem CI configurados hoje, e este slug **não** introduz
nenhum: seria mudança de infraestrutura fora do escopo. As checagens acima (esquema,
versionamento, subconjunto de `SAFE_KEYS`) são casos da própria suíte, para que
rodem com `py -3.13 test_biostools.py` sem depender de plataforma de CI.

## Documentação

Ao final da implementação, delegar ao agente `documentation` (ver `CLAUDE.md`):
- F-spec para o caminho universal de resposta (`find_setting` + índice);
- P-spec para qualquer teto encontrado (ex.: página cuja rolagem não termina,
  submenu inalcançável no modelo alvo);
- D-spec se alguma escolha de mecanismo for tomada (PgDn/PgUp vs. clique).
