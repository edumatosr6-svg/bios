"""O banco de perguntas: o instrumento com que K1-K4 são medidos.

K1 -- **zero respostas erradas** -- is the number this slug lives or dies
by, and a number is only as good as what it was measured against. Measured
against questions written by whoever wrote the code, K1 measures nothing:
the author already knows which phrasings the index happens to cover. So
the bank is an artefact of this slug, versioned in
`specs/cobertura-universal-bios/question-bank.md`, and at least ten of its
questions have to come from **a person who has not seen the
implementation**.

That requirement is not enforceable by a script, so what this module
enforces instead is the honest reporting of its absence: while the bank is
short of ten `nao-ensaiada` questions, `gate()` refuses and the KPI runner
reports K1-K4 as **NAO MEDIDO**. Reporting "K1 = 0" over rehearsed
questions only would be worse than reporting nothing -- a number that
looks like evidence and is not.

Format, one Markdown table row per question:

    | id | texto | origem | autor | expectativa |

`origem` is `ensaiada` or `nao-ensaiada`; `expectativa` is
`valor:<esperado>`, `nao-existe`, or `fora-de-escopo-escrita`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

BANK_PATH = (Path("specs") / "cobertura-universal-bios" / "question-bank.md")

ORIGINS = ("ensaiada", "nao-ensaiada")
EXPECT_NOT_EXIST = "nao-existe"
EXPECT_WRITE = "fora-de-escopo-escrita"
EXPECT_VALUE_PREFIX = "valor:"

# Thresholds from CA-F5.1/F5.3/F5.4.
MIN_QUESTIONS = 40
MIN_UNREHEARSED = 10
MIN_NOT_EXIST = 5
MIN_WRITE = 3


class BankInvalid(ValueError):
    """A malformed row. Always names the offending question."""


class BankIncomplete(ValueError):
    """Well-formed but too small to measure K1-K4 against."""


@dataclass
class Question:
    id: str
    text: str
    origin: str
    author: str
    expectation: str

    @property
    def expects_value(self):
        return self.expectation.startswith(EXPECT_VALUE_PREFIX)

    @property
    def expected_value(self):
        if not self.expects_value:
            return None
        return self.expectation[len(EXPECT_VALUE_PREFIX):].strip()


_ROW = re.compile(r"^\|(.+)\|\s*$")


HEADER = ("id", "texto", "origem", "autor", "expectativa")


def parse(text):
    """Every question row in a bank document.

    A table only counts as a question table once its header row reads
    exactly `| id | texto | origem | autor | expectativa |`, and it stops
    counting at the first line that is not a table row. The document is
    also documentation -- it explains its own format in a two-column
    table, and describes how to complete itself -- so "any pipe table is
    questions" would make the file unable to document itself. Inside a
    question table, on the other hand, EVERY row is a question: a row
    someone left half-filled is an error, not something to skip past.
    """
    questions = []
    in_table = False
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        match = _ROW.match(line)
        if not match:
            in_table = False
            continue
        cells = [c.strip() for c in match.group(1).split("|")]
        if tuple(c.lower() for c in cells) == HEADER:
            in_table = True
            continue
        if not in_table:
            continue
        if cells and all(set(c) <= set("-: ") for c in cells):
            continue
        if len(cells) != 5:
            raise BankInvalid(
                f"linha {number}: esperava 5 colunas "
                f"(id | texto | origem | autor | expectativa), veio "
                f"{len(cells)}: {line}")

        qid, qtext, origin, author, expectation = cells
        if not qid:
            raise BankInvalid(f"linha {number}: pergunta sem 'id'")
        if not qtext:
            raise BankInvalid(f"pergunta {qid!r}: 'texto' vazio")
        if origin not in ORIGINS:
            raise BankInvalid(
                f"pergunta {qid!r}: origem {origin!r} inválida "
                f"(esperado {' ou '.join(ORIGINS)})")
        if not author:
            raise BankInvalid(f"pergunta {qid!r}: 'autor' vazio -- quem "
                              f"escreveu importa, é o que K1 mede")
        if not (expectation in (EXPECT_NOT_EXIST, EXPECT_WRITE)
                or (expectation.startswith(EXPECT_VALUE_PREFIX)
                    and expectation[len(EXPECT_VALUE_PREFIX):].strip())):
            raise BankInvalid(
                f"pergunta {qid!r}: expectativa {expectation!r} inválida "
                f"(esperado 'valor:<esperado>', {EXPECT_NOT_EXIST!r} ou "
                f"{EXPECT_WRITE!r})")

        questions.append(Question(qid, qtext, origin, author, expectation))

    ids = [q.id for q in questions]
    duplicated = {i for i in ids if ids.count(i) > 1}
    if duplicated:
        raise BankInvalid(f"ids repetidos: {', '.join(sorted(duplicated))}")
    return questions


def load(path=BANK_PATH):
    path = Path(path)
    if not path.exists():
        raise BankInvalid(f"banco de perguntas ausente em {path}")
    return parse(path.read_text(encoding="utf-8"))


def counts(questions):
    return {
        "total": len(questions),
        "nao_ensaiada": sum(1 for q in questions if q.origin == "nao-ensaiada"),
        "nao_existe": sum(1 for q in questions
                          if q.expectation == EXPECT_NOT_EXIST),
        "fora_de_escopo_escrita": sum(1 for q in questions
                                      if q.expectation == EXPECT_WRITE),
    }


def shortfalls(questions):
    """Every threshold this bank misses, as sentences. Empty when complete."""
    n = counts(questions)
    problems = []
    if n["total"] < MIN_QUESTIONS:
        problems.append(f"banco incompleto: {n['total']} perguntas, "
                        f"mínimo {MIN_QUESTIONS}")
    if n["nao_ensaiada"] < MIN_UNREHEARSED:
        problems.append(f"banco incompleto: {n['nao_ensaiada']} perguntas não "
                        f"ensaiadas, mínimo {MIN_UNREHEARSED}")
    if n["nao_existe"] < MIN_NOT_EXIST:
        problems.append(f"banco incompleto: {n['nao_existe']} perguntas com "
                        f"expectativa '{EXPECT_NOT_EXIST}', mínimo "
                        f"{MIN_NOT_EXIST}")
    if n["fora_de_escopo_escrita"] < MIN_WRITE:
        problems.append(f"banco incompleto: {n['fora_de_escopo_escrita']} "
                        f"perguntas com expectativa '{EXPECT_WRITE}', mínimo "
                        f"{MIN_WRITE}")
    return problems


def gate(questions):
    """Raise `BankIncomplete` unless K1-K4 may honestly be measured.

    CA-F5.5. The message names the counts rather than saying "incomplete",
    because the person who has to fix it needs to know how many more
    unrehearsed questions to go and ask for.
    """
    problems = shortfalls(questions)
    if problems:
        raise BankIncomplete("; ".join(problems))
    return questions
