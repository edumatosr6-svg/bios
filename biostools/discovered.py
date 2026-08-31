"""Onde `explore_setting` ja achou algo, para nao varrer de novo.

Nao confundir com `index.py`. O indice oficial (`data/label_index.json`)
e um artefato COMMITADO: uma tour humana visitou toda pagina, de
proposito, e escreveu o que viu -- "toda entrada e CONFIRMADO", como o
proprio modulo diz. Este arquivo e o oposto disso em toda dimensao que
importa: nao e commitado (ver `.gitignore`), nao vem de uma tour completa
-- so registra o que uma varredura AVULSA de `explore_setting` encontrou
enquanto procurava UM termo especifico -- e por isso nunca deveria ser
tratado como o mesmo tipo de conhecimento. Misturar os dois no mesmo
arquivo teria corrompido o significado de "todo mundo aqui foi revisado",
que e exatamente a garantia que faz `find_setting` confiavel para o
indice oficial.

**O que e gravado, e o que deliberadamente nao e.** Uma entrada guarda
ONDE um rotulo foi lido (tela, submenu se houver) -- nunca o VALOR. Um
relogio muda a cada segundo e um Enabled/Disabled muda quando alguem mexe
na configuracao; a POSICAO de um campo numa pagina e o que fica estavel
entre uma pergunta e a proxima. `find_setting` usa isto para pular direto
para a tela certa, mas sempre le o valor DE NOVO, ao vivo -- nunca
responde com o que esta gravado aqui.

**Autoaprendizado sem revisao humana, decisao deliberada.** Diferente de
`labels.SUBMENUS` (que exige provenance=CONFIRMADO antes de navegar
automaticamente para um submenu), uma entrada aqui e confiavel assim que
gravada. A diferenca que justifica isso: um submenu declarado errado faz
o codigo tentar abrir algo que nao existe ou que é outra coisa -- um erro
de NAVEGACAO, silencioso, sobre o qual `screen.match_score` nao tem
como opinar de antemao. Uma entrada aqui errada faz, na pior hipotese,
`find_setting` chegar numa tela onde o rotulo nao esta (mais) --
`page.find_pair` simplesmente nao acha nada la, e o chamador cai de volta
para "nao existe", exatamente a mesma resposta honesta de sempre. Nao ha
caminho para uma entrada errada aqui produzir um VALOR errado: o valor
sempre vem de uma leitura ao vivo, verificada, no momento da pergunta.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import screen as screen_mod

# Cache por maquina, nao artefato revisado -- ver o docstring do modulo.
# Fora de `data/label_index.json` de proposito, para que uma ferramenta
# que so olhe o indice oficial (o validador de F3, por exemplo) nunca
# veja isto por engano.
DISCOVERED_PATH = Path("data") / "discovered_settings.json"


def _empty():
    return {"version": 1, "entries": []}


def load(path=DISCOVERED_PATH):
    """O cache em disco, ou uma estrutura vazia se ainda nao existe.

    Ausente nao e erro -- e o estado normal antes da primeira descoberta.
    Diferente de `index.IndexMissing`, que E um erro: o indice oficial
    tem que existir (uma tour ja rodou) para `find_setting` funcionar,
    enquanto este cache comecar vazio e exatamente o esperado num
    checkout novo.
    """
    if not path.exists():
        return _empty()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # Cache corrompido nao pode travar uma pergunta -- e so uma
        # aceleracao, nunca a fonte da verdade. Comeca vazio; a proxima
        # descoberta reescreve o arquivo do zero.
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return _empty()
    return data


def save(data, path=DISCOVERED_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def _key(entry):
    return (screen_mod.normalize(entry["label"]), entry["screen"],
            entry.get("submenu"))


def remember(label, screen, submenu=None, term=None, path=DISCOVERED_PATH):
    """Registra ONDE `label` foi lido, mesclando com uma entrada existente.

    Idempotente por `(rotulo normalizado, tela, submenu)`: perguntar pelo
    mesmo ajuste de formas diferentes ("hora do sistema", "que horas sao")
    atualiza UMA entrada (acumulando os termos vistos, uteis so para
    diagnostico) em vez de duplicar. `term`, quando dado, e o texto exato
    que o operador usou -- guardado por transparencia, nunca usado para
    casar contra outra pergunta (isso e trabalho de `screen.match_score`
    sobre o `label`, na hora da busca).
    """
    data = load(path)
    entry = {"label": label, "screen": screen, "submenu": submenu}
    target_key = _key(entry)

    for existing in data["entries"]:
        if _key(existing) == target_key:
            existing["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if term and term not in existing.setdefault("terms_seen", []):
                existing["terms_seen"].append(term)
            save(data, path)
            return existing

    entry["terms_seen"] = [term] if term else []
    entry["discovered_at"] = entry["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["entries"].append(entry)
    save(data, path)
    return entry


def search(term, path=DISCOVERED_PATH):
    """Toda entrada cujo rotulo casa com `term`, melhor score primeiro.

    `term` ja deve vir expandido (uma lista de grafias, o que
    `find_setting.concept_spellings` produz) -- este modulo nao conhece
    conceitos nem sinonimos, so casa contra o texto do rotulo gravado,
    exatamente como `index.search` faz contra o indice oficial. Mesmo
    algoritmo, fontes diferentes.
    """
    data = load(path)
    best_score, best = 0, []
    for entry in data["entries"]:
        score = screen_mod.match_score(term, entry.get("label", ""))
        if not score:
            continue
        if score > best_score:
            best_score, best = score, [entry]
        elif score == best_score:
            best.append(entry)
    return best_score, best


def forget(label, screen, submenu=None, path=DISCOVERED_PATH):
    """Remove uma entrada que se provou errada (a posicao nao tinha mais
    o rotulo quando `find_setting` tentou usa-la). Autocorrecao: a
    proxima pergunta sobre esse ajuste cai de volta em `explore_setting`,
    que varre de novo e regrava a posicao certa -- em vez de este cache
    continuar mandando para um lugar que ja mudou."""
    data = load(path)
    target_key = (screen_mod.normalize(label), screen, submenu)
    remaining = [e for e in data["entries"] if _key(e) != target_key]
    if len(remaining) != len(data["entries"]):
        data["entries"] = remaining
        save(data, path)
