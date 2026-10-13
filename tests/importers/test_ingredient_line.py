import pytest

from importers.ingredient_line import REASON_NO_NAME, REASON_NO_QUANTITY, parse_line


@pytest.mark.parametrize(
    ("raw", "name", "qty", "unit", "source_unit"),
    [
        # количество в начале, в конце, после тире и запятой, в скобках
        ("2 ст. л. масла", "масла", 30, "ml", "tbsp"),
        ("Мука — 200 г", "мука", 200, "g", "g"),
        ("Мука - 200 г", "мука", 200, "g", "g"),
        ("Мука, 200 г", "мука", 200, "g", "g"),
        ("Мука (200 г)", "мука", 200, "g", "g"),
        ("Мука 200г", "мука", 200, "g", "g"),
        ("500мл молока", "молока", 500, "ml", "ml"),
        # дроби и числительные словами
        ("1,5 стакана молока", "молока", 300, "ml", "cup"),
        ("1/2 ч. л. соли", "соли", 2.5, "ml", "tsp"),
        ("1 1/2 кг картофеля", "картофеля", 1500, "g", "kg"),
        ("½ стакана сахара", "сахара", 100, "ml", "cup"),
        ("полстакана риса", "риса", 100, "ml", "cup"),
        ("пол-литра воды", "воды", 500, "ml", "l"),
        ("полкило фарша", "фарша", 500, "g", "kg"),
        ("полторы ст. л. мёда", "меда", 22.5, "ml", "tbsp"),
        # штуки: с единицей и без
        ("Яйца 3 шт", "яйца", 3, "pcs", "pcs"),
        ("2 яйца", "яйца", 2, "pcs", "pcs"),
        ("2 средние луковицы", "средние луковицы", 2, "pcs", "pcs"),
        ("3 зубчика чеснока", "чеснока", 3, "pcs", "clove"),
        ("1 банка кукурузы", "кукурузы", 1, "pcs", "can"),
        ("1 пучок укропа", "укропа", 1, "pcs", "bunch"),
        ("1 щепотка перца", "перца", 0.5, "g", "pinch"),
        # проценты в названии не количество
        ("Сметана 20% 100 г", "сметана 20%", 100, "g", "g"),
        ("Молоко 3,2% — 500 мл", "молоко 3,2%", 500, "ml", "ml"),
        # пояснение после запятой отбрасывается
        ("1 луковица, нарезанная кубиками", "луковица", 1, "pcs", "pcs"),
        ("200 г куриной грудки, отварной", "куриной грудки", 200, "g", "g"),
        # регистр и ё
        ("2 Ст. Л. МЁДА", "меда", 30, "ml", "tbsp"),
        ("500\xa0г творога", "творога", 500, "g", "g"),
    ],
)
def test_parsed_ok(raw, name, qty, unit, source_unit):
    p = parse_line(raw)
    assert (p.name, p.qty, p.unit, p.source_unit) == (name, qty, unit, source_unit)
    assert p.status == "ok" and not p.needs_review and p.reason is None


@pytest.mark.parametrize(
    ("raw", "qty", "unit"),
    [
        ("2-3 зубчика чеснока", 3, "pcs"),
        ("1–1,5 л воды", 1500, "ml"),
        ("от 2 до 3 ст. л. масла", 45, "ml"),
    ],
)
def test_range_takes_upper_bound_and_marks_approx(raw, qty, unit):
    p = parse_line(raw)
    assert (p.qty, p.unit, p.approx) == (qty, unit, True)


def test_approx_word():
    p = parse_line("около 200 г сыра")
    assert (p.name, p.qty, p.approx) == ("сыра", 200, True)


@pytest.mark.parametrize(
    "raw",
    [
        "Соль по вкусу",
        "Перец по желанию",
        "Зелень для подачи",
        "Масло для жарки",
        "Соль на кончике ножа",
        "Немного укропа",
    ],
)
def test_to_taste_is_optional_without_quantity(raw):
    p = parse_line(raw)
    assert p.optional and p.qty is None and p.unit is None
    assert p.status == "to_taste" and not p.needs_review and p.name


def test_to_taste_with_quantity_keeps_both():
    p = parse_line("Соль 1 щепотка по вкусу")
    assert (p.name, p.qty, p.optional, p.status) == ("соль", 0.5, True, "ok")


@pytest.mark.parametrize("raw", ["Лавровый лист", "Укроп", "зелень"])
def test_no_quantity_needs_review(raw):
    p = parse_line(raw)
    assert p.needs_review and p.reason == REASON_NO_QUANTITY and p.name
    assert p.status == "needs_review"


@pytest.mark.parametrize("raw", ["", "   ", "200 г", "2 ст. л.", "по вкусу"])
def test_no_name_needs_review(raw):
    p = parse_line(raw)
    assert p.needs_review and p.reason == REASON_NO_NAME


def test_raw_text_is_kept():
    raw = "  2 ст. л. Масла  "
    assert parse_line(raw).raw == raw


def test_first_quantity_with_unit_wins_over_bare_number():
    # «2» — часть названия, количество с единицей — «150 г»
    p = parse_line("Печенье 2 вида, 150 г")
    assert (p.qty, p.unit) == (150, "g")


def test_quantity_found_in_parentheses_only_when_missing_outside():
    p = parse_line("Мука пшеничная (около 1,5 стакана)")
    assert (p.name, p.qty, p.unit, p.approx) == ("мука пшеничная", 300, "ml", True)


@pytest.mark.parametrize(
    ("raw", "name", "qty", "unit"),
    [
        ("Соль — щепотка", "соль", 0.5, "g"),
        ("щепотка соли", "соли", 0.5, "g"),
        ("пучок укропа", "укропа", 1, "pcs"),
        ("Лёд — 5-6 кубиков", "лед", 6, "pcs"),
    ],
)
def test_unit_without_number_means_one(raw, name, qty, unit):
    p = parse_line(raw)
    assert (p.name, p.qty, p.unit) == (name, qty, unit)


def test_list_without_quantity_keeps_all_names():
    # «соль, перец — по вкусу»: два продукта, запятая не пояснение
    p = parse_line("Соль, перец — по вкусу")
    assert (p.name, p.status) == ("соль, перец", "to_taste")


@pytest.mark.parametrize(
    "raw", ["Сливочное масло для формы", "Мука для присыпки", "Масло для обжарки"]
)
def test_for_pan_is_optional(raw):
    p = parse_line(raw)
    assert p.optional and p.qty is None and not p.needs_review


def test_unit_in_parentheses_beats_bare_number_outside():
    p = parse_line("Мука 2 сорт (около 1,5 стакана)")
    assert (p.qty, p.source_unit) == (300, "cup")


def test_first_bare_number_wins_when_there_are_several():
    p = parse_line("Печенье 2 вида 3 штуки без сахара 5")
    assert (p.qty, p.unit) == (3, "pcs")  # единица рядом с числом важнее порядка
    p = parse_line("Конфеты 2 вида 5")
    assert (p.qty, p.unit, p.source_unit) == (2, "pcs", "pcs")


def test_bare_number_only_in_parentheses():
    p = parse_line("Яйца (3)")
    assert (p.name, p.qty, p.unit) == ("яйца", 3, "pcs")
