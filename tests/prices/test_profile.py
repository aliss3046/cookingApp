import json

import pytest

from prices.profile import (
    ProfileError,
    StoreDisabled,
    load_profiles,
    parse_profile,
)

APPROVAL = {"by": "владелец проекта", "on": "2026-10-14", "basis": "решение в чате"}


def raw(**kw):
    base = {"name": "Тест", "base_url": "https://shop.test", "min_delay_s": 20}
    return {**base, **kw}


def test_shipped_profiles_load_and_enabled_ones_are_approved():
    profiles = load_profiles()
    assert {"magnit", "dixy"} <= set(profiles)
    for p in profiles.values():
        assert p.min_delay_s >= 20 and p.daily_request_limit <= 500
        if p.enabled:
            assert p.approval is not None and p.categories
            p.require_enabled()
        else:
            with pytest.raises(StoreDisabled, match="выключен"):
                p.require_enabled()


def test_enabled_requires_a_complete_approval():
    with pytest.raises(ProfileError, match="без записи approval"):
        parse_profile("x", raw(enabled=True))
    for bad in ({"by": "я"}, {"by": "я", "on": "2026-10-14"}, {"on": "d", "basis": "b"}):
        with pytest.raises(ProfileError, match="approval требует"):
            parse_profile("x", raw(enabled=True, approval=bad))
    p = parse_profile("x", raw(enabled=True, approval=APPROVAL))
    p.require_enabled()  # не бросает
    assert p.approval.by == "владелец проекта" and p.approval.on == "2026-10-14"


def test_approval_without_enabling_does_not_turn_the_store_on():
    p = parse_profile("x", raw(approval=APPROVAL))
    assert not p.enabled
    with pytest.raises(StoreDisabled):
        p.require_enabled()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"base_url": "http://shop.test"}, "https"),
        ({"base_url": "shop.test"}, "https"),
        ({"min_delay_s": 5}, "меньше минимума"),
        ({"daily_request_limit": 0}, "лимит"),
        ({"daily_request_limit": 501}, "лимит"),
    ],
)
def test_limits_and_urls_are_validated(kwargs, message):
    with pytest.raises(ProfileError, match=message):
        parse_profile("x", raw(**kwargs))


def test_categories_are_validated_against_the_store_host():
    ok = {"url": "https://shop.test/cat/milk", "groups": ["молочные"], "note": "Молоко"}
    p = parse_profile(
        "x", raw(categories=[ok, {"url": "https://shop.test/cat/x", "ingredients": ["egg"]}])
    )
    assert p.categories[0].groups == ("молочные",) and p.categories[1].ingredients == ("egg",)
    for bad, message in [
        ({"url": "https://other.test/cat", "groups": ["g"]}, "должен быть https и на shop.test"),
        ({"url": "http://shop.test/cat", "groups": ["g"]}, "должен быть https"),
        ({"url": "https://shop.test/cat"}, "ни группы, ни ингредиенты"),
        ({"groups": ["g"]}, "должен быть https"),
    ]:
        with pytest.raises(ProfileError, match=message):
            parse_profile("x", raw(categories=[bad]))


def test_load_profiles_skips_comments(tmp_path):
    f = tmp_path / "stores.json"
    f.write_text(json.dumps({"_comment": "x", "a": raw()}), encoding="utf-8")
    assert list(load_profiles(f)) == ["a"]


def test_source_defaults_to_http_and_saved_needs_a_folder():
    assert parse_profile("x", raw()).source == "http"
    p = parse_profile("x", raw(source="saved", pages_dir="pages/x"))
    assert (p.source, p.pages_dir) == ("saved", "pages/x")
    with pytest.raises(ProfileError, match="pages_dir"):
        parse_profile("x", raw(source="saved"))
    with pytest.raises(ProfileError, match="source должен быть"):
        parse_profile("x", raw(source="stealth"))
