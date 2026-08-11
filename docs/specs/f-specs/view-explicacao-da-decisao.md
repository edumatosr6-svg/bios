# View de explicação da decisão (`--explain`)

## Objetivo
View que abre a aritmética por trás do que o motor de percepção concluiu — regiões, grupos, classes e, para cada classe usável, **cada canal do E7 com o desvio medido de cada membro** — para que uma resposta errada possa ser lida de volta até o estágio que a produziu.

Existe porque o motor era construído para se abster em vez de chutar e registrava *que* se absteve, mas não registrava a conta de nenhum dos dois desfechos: o E7 guardava o vencedor de cada canal e descartava a medição de todos os outros membros. Consequência: `selected: X` e "nada se destacou" pareciam igualmente confiáveis de fora, mesmo quando um dos dois era ruído que cruzou um limiar por acaso. Essa era exatamente a informação necessária para distinguir "este elemento se destacou" de "nada se destacou e o vencedor é ruído" — e uma resposta que o motor não consegue justificar vale pouco mais que resposta nenhuma (§F4, proveniência obrigatória, em `../../architecture/PERCEPTION_PIPELINE_SPEC.md`).

## Escopo
- **Dentro**: `perception/explain.py` (módulo novo, função `explain(perception) -> str`), flag `--explain` em `perception/run.py`, e a separação entre medição e decisão no E7 (`perception/stages/e7_state.py::measure`, nova e pública).
- **Fora**: não muda nenhuma decisão nem nenhum número do motor — é uma view de leitura sobre a mesma `Perception`. Não altera o contrato serializado do E10; não substitui `--summary`, `--trace` nem `--view full`.

## Comportamento esperado
```
py -3.13 -m perception.run --source file --input IMAGEM.png --explain
```
Imprime, em ordem, a cadeia inteira:

1. **Superfície** — dimensões e se foi retificada.
2. **Regiões** — onde comparar é legítimo: geometria, nº de primitivas, quantas com texto.
3. **Grupos** — eixo, pitch, regularidade de ritmo e os membros.
4. **Classes** — role, tamanho, se é usável como referência e o motivo quando não é.
5. **Medições por canal**, só para classes usáveis. Para cada canal (`S1_background`, `S2_chroma`, `S3_polarity`): o veredito explícito contra cada limiar (`MIN_DEVIATION`, `RUNNER_UP_RATIO`), a **dispersão medida** da classe, e o **desvio de cada membro**, com vencedor e segundo colocado marcados. Membros sem valor no descritor aparecem listados à parte (`not measurable on this channel`); canal sem medição possível diz por quê.
6. **Conclusão** — os estados reportados, com confiança, canais que concordaram e a evidência por canal.
7. **Não decidiu** — as abstenções agregadas por estágio e motivo.

A dispersão medida vem marcada com `FLOORED -- class uniform to within sensor noise` quando fica abaixo do `NOISE_FLOOR`, isto é, quando a classe é uniforme dentro do ruído do sensor e todo desvio calculado dali é razão contra um número que a medição não resolve.

**Como ler**: classe cujo vencedor bate o segundo colocado com folga larga é sinal real. Classe em que todos os membros ficam num desvio parecido e o vencedor raspa no limiar é o motor achando *alguma coisa* na ausência do marcador que a interface de fato usa — assinatura de **canal faltando**, não de estado presente.

## Detalhes técnicos
**Medição separada da decisão.** O E7 foi refatorado: `measure(perception, klass, descriptor, direction)` devolve `(deviations, values, spreads)` e tanto `_evaluate` (a decisão) quanto o explicador passam por ela. Isso é o que impede a explicação de divergir da decisão que ela alega explicar — não há um segundo caminho de cálculo para a view.

**`spreads` é a dispersão antes do piso.** `measure` devolve o `raw_spread` medido, não o `max(raw_spread, NOISE_FLOOR)` usado na divisão. É essa distinção que permite ver quando o piso de ruído está fazendo todo o trabalho, em vez de só ver o número final já corrigido.

**Valor demonstrado na prática (2026-08-10)**: foi esta view que mostrou que a primeira hipótese de correção do falso positivo em classe fina estava errada — a regra intuitiva ("exigir corroboração quando a classe é uniforme") não discrimina, porque a classe correta e a de ruído estão **ambas** abaixo do `NOISE_FLOOR`. Sem a view, a regra errada teria sido implementada e teria *parecido* funcionar no frame de teste. Ver `../p-specs/classe-fina-canal-unico-eleito-por-ruido.md`.

Foi também a view que evidenciou o teto do canal de borda: `S3_polarity` dando **0.00 para todos os membros de todas as classes** nas telas da Positivo (canal morto ali) e `S2_chroma` apontando para itens diferentes do `S1_background` na mesma classe — ver `../p-specs/campo-focado-por-borda-sem-canal-no-e7.md`.

## Critérios de aceite
- `--explain` roda sobre qualquer imagem que o motor já processa e imprime a cadeia sem alterar estados nem abstenções (é uma leitura da mesma `Perception`).
- Os desvios impressos são idênticos aos que a decisão usou, por construção: o mesmo `measure()`.
- Sem teste automatizado — como o resto do motor, não existe `test_perception.py` (ver `motor-percepcao-interface.md`, "Questões em aberto").

## Status
Concluída — 2026-08-10.
