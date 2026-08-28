# Testes — KPIs

Como cada KPI de `software-specs.md` é medido. Os KPIs de banco de perguntas
(K1–K4) exigem a máquina alvo; os demais rodam no CI sem hardware.

## Banco de perguntas

Artefato **entregue por F5**: `specs/cobertura-universal-bios/question-bank.md`,
versionado. Não é pressuposto do slug — é produzido por ele.

- ≥ 40 perguntas em texto livre sobre esta máquina.
- ≥ 10 marcadas `nao-ensaiada`, escritas por **uma pessoa** que não viu a
  implementação. **O impl-loop não pode gerá-las** (CA-F5.3).
- ≥ 5 com expectativa `nao-existe`; ≥ 3 com `fora-de-escopo-escrita`.
- Cada pergunta tem `id`, `texto`, `origem`, `autor`, `expectativa`.

### CT-K14 — Validador de formato do banco (K14, sem hardware)
- **Dado** `question-bank.md`
- **Quando** o validador roda
- **Então** ele confere as contagens acima e o formato de cada linha
- **E** falha nomeando a pergunta malformada

### CT-K0 — Banco incompleto bloqueia K1–K4 (CA-F5.5)
- **Dado** um banco com apenas 3 perguntas `nao-ensaiada`
- **Quando** o runner de KPIs executa
- **Então** ele **falha** com "banco incompleto: 3 perguntas não ensaiadas, mínimo 10"
- **E** não reporta K1–K4
- (Um K1 = 0 medido só sobre perguntas ensaiadas é enganoso — pior que ausente.)

Runner: um script de bancada que, para cada pergunta, roda o caminho de resposta
completo (tool nomeada quando houver, senão `find_setting`), cronometra e classifica
o desfecho em uma de três classes:
- **correta** — valor devolvido confere com a expectativa;
- **abstenção honesta** — sem valor, com afirmação de inexistência ou de ambiguidade,
  coerente com a expectativa;
- **errada** — valor devolvido diverge da expectativa, OU afirmação de inexistência
  para um ajuste que existe, OU aceitação de um pedido de escrita.

### CT-K1 — Zero respostas erradas (K1)
- **Então** a contagem da classe **errada** é 0. Qualquer valor > 0 reprova o slug,
  independentemente dos outros números.

### CT-K2 — Fração correta ≥ 80% (K2)
- **Então** correta / total ≥ 0,80

### CT-K3 — Qualidade da abstenção (K3)
- **Dado** toda resposta do banco com `value=None`
- **Então** 100% delas trazem em `notes` o escopo da busca: telas e submenus cobertos
  pelo índice + `captured_at`
- **E** 100% usam a formulação de inexistência ("não existe na BIOS desta máquina"),
  distinta da mensagem de falha
- **E** nenhuma é um "não achei" sem escopo
- Este KPI **pode falhar sozinho**, com K1 = 0 e K2 ≥ 80%: uma abstenção sem escopo é
  ambígua para o operador mesmo sendo tecnicamente honesta.

### CT-K4 — Tempo de resposta (K4)
- **Então** p95 do tempo ponta a ponta ≤ 30 s
- **E** nenhuma pergunta ultrapassa 60 s

## KPIs verificáveis sem hardware

### CT-K5 — Cobertura da Main (K5)
- Ver `f1-leitura-pagina-inteira.md` CT-F1.9 (fixture de 73 linhas) e CT-F1.13
  `[BANCADA]`.

### CT-K6 — Submenus alcançáveis (K6)
- Sem hardware: `f2-submenus.md` prova a mecânica.
- Com hardware: o cabeçalho `visited` de `data/label_index.json` lista ≥ 8 submenus
  de Advanced. Asserção sobre o arquivo commitado, roda no CI.

### CT-K7 — Teclas fora de `SAFE_KEYS` (K7)
- `r1-somente-leitura.md` CT-R1.2. Meta: 0.

### CT-K8 — Visitas a `save_and_exit` (K8)
- `f3-indice.md` CT-F3.7 e `r1-somente-leitura.md` CT-R6.1. Meta: 0.

### CT-K9 — Entradas de índice inválidas (K9)
- Validador de esquema sobre `data/label_index.json`: contagem de entradas sem
  `screen_index` ou sem `provenance == "CONFIRMADO"` é 0.

### CT-K10 — Índice versionado (K10)
- `git ls-files data/label_index.json` retorna o caminho; arquivo tem ≥ 1 entrada.

### CT-K11 — Uma sessão por execução (K11)
- `f3-indice.md` CT-F3.9 e `r1-somente-leitura.md` CT-R4.1. Meta: 1.

### CT-K12 — Grafias CONFIRMADO sem evidência (K12)
- `f0-bootstrap.md` CT-F0.9. Meta: 0.

### CT-K13 — Submenus alvo declarados (K13)
- `f0-bootstrap.md` CT-F0.8. Meta: 8 de 8.

## Gate de conclusão

O runner reporta dois blocos separados, para que não se confundam:
- **Bloco automático** (K5–K14, sem hardware exceto onde marcado): é o que o
  impl-loop pode fechar sozinho.
- **Bloco de bancada** (K1–K4): exige a máquina alvo **e** F5 completo com as
  perguntas não ensaiadas escritas por humano. Enquanto não houver, o runner reporta
  `NAO MEDIDO` — nunca um valor otimista.

## Relatório

O runner escreve um relatório com as contagens das três classes, os tempos, e a lista
nominal das perguntas de cada classe — para que uma resposta errada seja
identificável, não só contada.
