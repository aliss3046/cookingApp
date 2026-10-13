import io
import json
from pathlib import Path

import pytest

from importers.__main__ import EXIT_IMPORT_FAILED, EXIT_OK, main
from importers.directory import load_directory
from importers.recipe_page import DisallowedByRobots

PAGES = Path(__file__).parent / "fixtures" / "pages"


@pytest.fixture(scope="module")
def directory():
    return load_directory()


def run(argv, directory, fetch=None):
    out, err = io.StringIO(), io.StringIO()
    kwargs = {"fetch": fetch} if fetch else {}
    code = main(argv, directory=directory, out=out, err=err, **kwargs)
    return code, out.getvalue(), err.getvalue()


def test_url_prints_recipe_input(directory):
    seen = []

    def fetch(url):
        seen.append(url)
        return (PAGES / "graph_recipe.html").read_text("utf-8")

    code, out, err = run(["https://recipes.test/borsch?utm=1"], directory, fetch)
    assert (code, err) == (EXIT_OK, "") and seen == ["https://recipes.test/borsch?utm=1"]
    data = json.loads(out)
    assert data["recipe"]["status"] == "draft"
    assert data["recipe"]["source_url"] == "https://recipes.test/borsch?utm=1"
    assert data["summary"] == {"lines": 7, "needs_review": 0} and data["review"] == []
    assert out.count("\n") > 10  # по умолчанию с отступами


def test_html_file_compact_with_review(directory, tmp_path):
    f = tmp_path / "page.html"
    f.write_text(
        '<script type="application/ld+json">{"@type": "Recipe", "name": "Тест",'
        ' "recipeIngredient": ["Масло — 20 г", "Мука — 200 г"]}</script>',
        encoding="utf-8",
    )
    code, out, _ = run(["--html", str(f), "--compact"], directory)
    assert code == EXIT_OK and out.count("\n") == 1
    data = json.loads(out)
    assert data["warnings"] == ["servings_unknown"]
    assert data["review"] == [
        {
            "raw_text": "Масло — 20 г",
            "name": "масло",
            "reason": "ambiguous",
            "candidates": data["review"][0]["candidates"],
        }
    ]
    assert len(data["review"][0]["candidates"]) > 1


def test_import_error_goes_to_stderr(directory):
    def fetch(url):
        raise DisallowedByRobots("robots.txt запрещает")

    code, out, err = run(["https://x.test/r"], directory, fetch)
    assert (code, out) == (EXIT_IMPORT_FAILED, "") and "robots.txt запрещает" in err


def test_missing_html_file(directory, tmp_path):
    code, out, err = run(["--html", str(tmp_path / "nope.html")], directory)
    assert code == EXIT_IMPORT_FAILED and out == "" and "Не удалось" in err


def test_url_and_html_are_exclusive(directory, tmp_path):
    with pytest.raises(SystemExit):
        run(["https://x.test/r", "--html", str(tmp_path / "x.html")], directory)
    with pytest.raises(SystemExit):
        run([], directory)


def test_loads_directory_by_default(monkeypatch):
    import importers.__main__ as cli

    loaded = []
    monkeypatch.setattr(cli, "load_directory", lambda: loaded.append(1) or load_directory())
    out = io.StringIO()
    code = cli.main(["--html", str(PAGES / "plain_recipe.html")], out=out, err=io.StringIO())
    assert code == EXIT_OK and loaded == [1]
