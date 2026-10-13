import pytest

from importers.units import UNIT_DEFS, match_unit, to_base


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("ст. л. масла", "tbsp"),
        ("ст.л. масла", "tbsp"),
        ("столовые ложки", "tbsp"),
        ("столовая ложка", "tbsp"),
        ("ст. ложки", "tbsp"),
        ("ч. л.", "tsp"),
        ("ч.л.", "tsp"),
        ("чайные ложки", "tsp"),
        ("десертная ложка", "dsp"),
        ("стакана", "cup"),
        ("стаканов", "cup"),
        ("кг", "kg"),
        ("килограмма", "kg"),
        ("г", "g"),
        ("гр.", "g"),
        ("грамм", "g"),
        ("граммов", "g"),
        ("мл", "ml"),
        ("миллилитров", "ml"),
        ("л", "l"),
        ("литра", "l"),
        ("шт.", "pcs"),
        ("штуки", "pcs"),
        ("зубчика", "clove"),
        ("щепотки", "pinch"),
        ("горсти", "handful"),
        ("пучок", "bunch"),
        ("банки", "can"),
        ("пачки", "pack"),
        ("бутылки", "bottle"),
        ("ломтика", "slice"),
        ("головки", "head"),
        ("веточки", "sprig"),
    ],
)
def test_match_unit(text, code):
    got = match_unit(text, 0)
    assert got is not None and got[0] == code


@pytest.mark.parametrize("text", ["грецких орехов", "лимона", "стой", "горох", "мука", "", "яйца"])
def test_match_unit_does_not_eat_words(text):
    # «г» не должна отъедать «грецких», «л» — «лимона», «ст» — «стой»
    assert match_unit(text, 0) is None


def test_match_unit_at_position():
    text = "200 г муки"
    assert match_unit(text, 4) == ("g", 5)
    assert match_unit(text, 0) is None


@pytest.mark.parametrize(
    ("qty", "code", "want"),
    [
        (2, "kg", (2000, "g")),
        (1.5, "l", (1500, "ml")),
        (2, "tbsp", (30, "ml")),
        (3, "tsp", (15, "ml")),
        (1, "cup", (200, "ml")),
        (1, "pinch", (0.5, "g")),
        (4, "clove", (4, "pcs")),
        (2, "g", (2, "g")),
    ],
)
def test_to_base(qty, code, want):
    assert to_base(qty, code) == want


def test_all_units_have_known_base():
    assert {u.base for u in UNIT_DEFS.values()} == {"g", "ml", "pcs"}
