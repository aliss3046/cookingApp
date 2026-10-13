import pytest

from importers.text import normalize, stem, stems, tokens


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("морковь", "моркови"),
        ("лук", "лука"),
        ("чеснок", "чеснока"),
        ("перец", "перца"),
        ("огурец", "огурцы"),
        ("кабачок", "кабачки"),
        ("горошек", "горошка"),
        ("молоко", "молока"),
        ("сливочное", "сливочного"),
        ("помидоры", "помидоров"),
        ("соль", "соли"),
        ("масло", "масла"),
    ],
)
def test_word_forms_share_stem(a, b):
    assert stem(a) == stem(b)


def test_short_words_are_not_cut_to_nothing():
    assert stem("сыр") == "сыр"
    assert stem("лук") == "лук"
    assert stem("сок") == "сок"


def test_long_ending_needs_longer_stem():
    # «салями» не должна совпасть с «сало»
    assert stem("салями") != stem("сало")


def test_normalize_and_tokens():
    assert normalize("  Лук-Порей  Ёмкий ") == "лук порей емкий"
    assert tokens("Молоко 3,2% — 500 мл") == ["молоко", "мл"]


def test_stems_ignore_order_stop_words_and_descriptors():
    assert stems("масло сливочное") == stems("сливочное масло")
    assert stems("томаты в собственном соку") == stems("томаты собственном соку")
    assert stems("свежий крупный укроп") == stems("укроп")
    assert stems("") == frozenset()
