import pytest

from importers.errors import FetchFailed
from prices.saved_pages import SavedPages, page_filename


def test_filename_follows_the_url_path():
    url = "https://dixy.ru/catalog/ovoshchi-frukty/ovoshchi/?x=1"
    assert page_filename(url) == "catalog_ovoshchi-frukty_ovoshchi.html"
    assert page_filename("https://dixy.ru/") == "index.html"


def test_reads_saved_page_and_reports_missing(tmp_path):
    (tmp_path / "catalog_milk.html").write_text("<html>молоко</html>", encoding="utf-8")
    pages = SavedPages(tmp_path)
    assert pages.get("https://dixy.ru/catalog/milk/") == "<html>молоко</html>"
    with pytest.raises(FetchFailed, match=r"catalog_eggs\.html"):
        pages.get("https://dixy.ru/catalog/eggs/")
