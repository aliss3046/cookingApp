"""Разбор robots.txt по RFC 9309: шаблоны с `*` и `$`, самое длинное правило побеждает.

Стандартный `urllib.robotparser` шаблонов не понимает: `Disallow: /*search` он считает
буквальным началом пути и ничего не запрещает. У магазинов все правила записаны шаблонами,
поэтому используется этот модуль.

Политика осторожности (строже RFC): если robots.txt прочитать не удалось (403, сетевой сбой,
5xx), ходить на сайт нельзя. Стандарт в таком случае (4xx) разрешает всё, но 403 на robots.txt
означает, что сайт не хочет автоматических клиентов.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

_RULE = re.compile(r"^\s*(user-agent|allow|disallow|crawl-delay|sitemap)\s*:\s*(.*?)\s*$", re.I)


@dataclass(frozen=True)
class Rule:
    allow: bool
    pattern: str

    def matches(self, path: str) -> bool:
        return _compile(self.pattern).match(path) is not None

    @property
    def specificity(self) -> int:
        return len(self.pattern)


_CACHE: dict[str, re.Pattern[str]] = {}


def _compile(pattern: str) -> re.Pattern[str]:
    cached = _CACHE.get(pattern)
    if cached is None:
        body = re.escape(pattern).replace(r"\*", ".*")
        if body.endswith(r"\$"):
            body = body[:-2] + "$"
        cached = _CACHE[pattern] = re.compile(body)
    return cached


@dataclass
class Group:
    agents: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    crawl_delay: float | None = None


@dataclass(frozen=True)
class Robots:
    groups: tuple[Group, ...]
    sitemaps: tuple[str, ...] = ()
    # robots.txt не удалось прочитать: всё запрещено (см. политику осторожности)
    unreadable: bool = False

    def _group_for(self, user_agent: str) -> Group | None:
        token = user_agent.split("/")[0].split()[0].lower()
        best: tuple[int, Group] | None = None
        for g in self.groups:
            for agent in g.agents:
                a = agent.lower()
                if a == "*":
                    continue
                if a in token and (best is None or len(a) > best[0]):
                    best = (len(a), g)
        if best:
            return best[1]
        return next((g for g in self.groups if "*" in [a.lower() for a in g.agents]), None)

    def allowed(self, user_agent: str, url: str) -> bool:
        if self.unreadable:
            return False
        group = self._group_for(user_agent)
        if group is None:
            return True
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        best: Rule | None = None
        for rule in group.rules:
            if not rule.pattern or not rule.matches(path):
                continue  # пустой Disallow разрешает всё
            if (
                best is None
                or rule.specificity > best.specificity
                or (rule.specificity == best.specificity and rule.allow and not best.allow)
            ):
                best = rule
        return best is None or best.allow

    def crawl_delay(self, user_agent: str) -> float | None:
        group = self._group_for(user_agent)
        return group.crawl_delay if group else None


UNREADABLE = Robots(groups=(), unreadable=True)


def parse_robots(text: str) -> Robots:
    groups: list[Group] = []
    sitemaps: list[str] = []
    current: Group | None = None
    collecting_agents = False
    for raw in text.splitlines():
        m = _RULE.match(raw.split("#", 1)[0])
        if not m:
            continue
        key, value = m[1].lower(), m[2]
        if key == "sitemap":
            sitemaps.append(value)
        elif key == "user-agent":
            if current is None or not collecting_agents:
                current = Group()
                groups.append(current)
            current.agents.append(value)
            collecting_agents = True
        elif current is not None:
            collecting_agents = False
            if key == "crawl-delay":
                try:
                    current.crawl_delay = float(value)
                except ValueError:
                    pass
            else:
                current.rules.append(Rule(allow=key == "allow", pattern=value))
    return Robots(groups=tuple(groups), sitemaps=tuple(sitemaps))
