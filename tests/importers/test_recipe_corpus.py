"""Качество разбора на 20 рецептах (docs: «не менее 90% строк без ручной правки»).

Корпус составлен авторами правил, поэтому тест защищает от регрессий, но не заменяет
проверку на реальных страницах рецептов: её нужно повторить, когда появится импорт по ссылке.
"""

import json
from pathlib import Path

from importers.ingredient_line import parse_line

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "recipes.json").read_text("utf-8"))

# Строки, которые правила честно не разбирают: нет ни количества, ни «по вкусу».
EXPECTED_REVIEW = {"Красный перец чили"}


def test_corpus_size():
    assert len(CORPUS) == 20


def test_at_least_90_percent_parse_without_review():
    lines = [line for r in CORPUS for line in r["lines"]]
    parsed = [parse_line(line) for line in lines]
    review = {p.raw for p in parsed if p.needs_review}
    assert len(review) / len(lines) <= 0.10, review
    # никаких неожиданных новых и пропавших «на проверку»: список меняется осознанно
    assert review == EXPECTED_REVIEW


def test_every_ok_line_has_positive_base_quantity():
    for r in CORPUS:
        for line in r["lines"]:
            p = parse_line(line)
            if p.status == "ok":
                assert p.qty is not None and p.qty > 0 and p.unit in {"g", "ml", "pcs"}, line
                assert p.name, line
