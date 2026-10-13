"""Страницы, сохранённые из обычного браузера (для магазинов, которые не отдают их программам).

Если магазин отвечает программе отказом (Дикси: 403), блокировка не обходится: страницу открывает
человек в своём браузере и сохраняет (`Ctrl+S`, «Веб-страница, только HTML») в папку. Имя файла —
путь адреса: `https://dixy.ru/catalog/ovoshchi-frukty/ovoshchi/` →
`catalog_ovoshchi-frukty_ovoshchi.html`.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from importers.errors import FetchFailed


def page_filename(url: str) -> str:
    path = urlsplit(url).path.strip("/")
    return (path.replace("/", "_") or "index") + ".html"


class SavedPages:
    """Тот же интерфейс `get(url)`, что у `PoliteFetcher`, но без сети."""

    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)

    def get(self, url: str) -> str:
        file = self.folder / page_filename(url)
        if not file.is_file():
            raise FetchFailed(f"нет сохранённой страницы {file.name}")
        return file.read_text(encoding="utf-8", errors="replace")
