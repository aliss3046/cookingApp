import pytest

from importers.quantities import find_quantities, to_float


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("2", 2),
        ("1,5", 1.5),
        ("1.5", 1.5),
        ("1/2", 0.5),
        ("1 1/2", 1.5),
        ("3 / 4", 0.75),
        ("½", 0.5),
        ("1½", 1.5),
        ("2 ⅓", 2 + 1 / 3),
    ],
)
def test_to_float(text, want):
    assert to_float(text) == pytest.approx(want)


def test_to_float_zero_denominator():
    with pytest.raises(ValueError, match="zero denominator"):
        to_float("1/0")


def test_find_quantities_positions_and_ranges():
    [q] = find_quantities("мука 200 г")
    assert (q.low, q.high, q.is_range) == (200, 200, False)
    assert "мука 200 г"[q.start : q.end] == "200"

    [q] = find_quantities("2-3 зубчика")
    assert (q.low, q.high, q.is_range) == (2, 3, True)

    [q] = find_quantities("от 2 до 3 штук")
    assert (q.low, q.high) == (2, 3)

    [q] = find_quantities("1 – 1,5 л")
    assert (q.low, q.high) == (1, 1.5)


def test_find_quantities_skips_percent_and_words():
    # проценты и цифры внутри слов не количества
    assert [(q.low) for q in find_quantities("молоко 3,2% 500 мл")] == [500]
    assert find_quantities("яйца с1") == []
    assert find_quantities("мука") == []
    assert [q.low for q in find_quantities("сыр 45% 100 г")] == [100]


def test_find_quantities_reversed_range_takes_first():
    [q] = find_quantities("5-3 шт")
    assert (q.low, q.high) == (5, 5)


def test_find_quantities_ignores_zero_denominator():
    assert find_quantities("1/0 ложки") == []
