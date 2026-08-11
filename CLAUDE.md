# CLAUDE.md

## Documentação

Este projeto tem um agente dedicado para documentação: `documentation` (`.claude/agents/documentation.md`). Ele sabe a taxonomia de `docs/` (f-specs, p-specs, d-specs, architecture, reference, studies, planning) — não precisa ser instruído sobre onde salvar nem onde procurar.

Delegue a ele proativamente, sem esperar o usuário pedir, sempre que:
- uma feature/comportamento novo for implementado e ainda não tiver F-spec em `docs/specs/f-specs/`;
- um problema/limite/"teto" for encontrado ou antecipado, mesmo que ainda não resolvido — vira P-spec em `docs/specs/p-specs/`;
- uma ferramenta, pacote, modelo ou dependência for escolhida/trocada/avaliada — vira D-spec em `docs/specs/d-specs/`;
- um estudo/experimento for concluído;
- uma decisão de arquitetura for tomada;
- houver um `.md` solto na raiz do projeto que devia estar organizado.

Delegue a ele também quando o usuário trouxer uma **ideia ou dúvida** sobre o projeto ("como a gente lida com X", "já tentamos Y antes?", "que ferramenta tá usando pra Z") — ele deve buscar nos docs e responder direto, citando a fonte, não só apontar uma pasta.

O usuário não quer precisar pedir "documenta isso" nem dizer onde salvar ou procurar toda vez — isso é o trabalho do agente.
