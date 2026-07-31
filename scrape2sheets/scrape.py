"""Парсер статических страниц: requests + BeautifulSoup, CSS-селекторы из конфига."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
RETRYABLE = {429, 500, 502, 503, 504}


@dataclass
class SiteConfig:
    """Описание одного сайта. Селекторы задаются в YAML, код не меняется."""

    name: str
    start_url: str
    item_selector: str
    fields: dict[str, str]  # имя колонки -> CSS-селектор внутри карточки
    attrs: dict[str, str] = field(default_factory=dict)  # колонка -> атрибут вместо текста
    next_selector: str | None = None
    max_pages: int = 1
    delay: float = 1.0


class Scraper:
    def __init__(self, timeout: float = 20.0, attempts: int = 4, proxy: str | None = None):
        self.timeout = timeout
        self.attempts = attempts
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_UA})
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})

    def fetch(self, url: str) -> str:
        delay = 1.0
        for attempt in range(1, self.attempts + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code in RETRYABLE and attempt < self.attempts:
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                # Без charset в Content-Type requests молча берёт ISO-8859-1,
                # и UTF-8 превращается в мусор вида "Â£51.77".
                if "charset" not in resp.headers.get("Content-Type", "").lower():
                    resp.encoding = resp.apparent_encoding or "utf-8"
                return resp.text
            except requests.RequestException as exc:
                if attempt == self.attempts:
                    raise
                sleep = delay + random.uniform(0, delay * 0.3)
                log.warning("%s — %s, повтор через %.1f с", url, exc, sleep)
                time.sleep(sleep)
                delay = min(delay * 2, 30.0)
        raise RuntimeError("недостижимо")

    def parse_page(self, html: str, cfg: SiteConfig, base_url: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        out: list[dict[str, Any]] = []
        for card in soup.select(cfg.item_selector):
            row: dict[str, Any] = {"_source": cfg.name}
            for column, selector in cfg.fields.items():
                el = card.select_one(selector)
                if el is None:
                    row[column] = ""
                    continue
                attr = cfg.attrs.get(column)
                if attr:
                    value = el.get(attr, "")
                    row[column] = urljoin(base_url, value) if attr == "href" else value
                else:
                    row[column] = el.get_text(strip=True)
            out.append(row)
        return out

    def crawl(self, cfg: SiteConfig) -> list[dict[str, Any]]:
        url: str | None = cfg.start_url
        rows: list[dict[str, Any]] = []
        for page in range(cfg.max_pages):
            if not url:
                break
            log.info("[%s] страница %d: %s", cfg.name, page + 1, url)
            html = self.fetch(url)
            batch = self.parse_page(html, cfg, url)
            log.info("[%s] найдено карточек: %d", cfg.name, len(batch))
            rows.extend(batch)
            url = self._next_url(html, cfg, url)
            if url:
                time.sleep(cfg.delay)
        return rows

    @staticmethod
    def _next_url(html: str, cfg: SiteConfig, current: str) -> str | None:
        if not cfg.next_selector:
            return None
        el = BeautifulSoup(html, "html.parser").select_one(cfg.next_selector)
        href = el.get("href") if el else None
        return urljoin(current, href) if href else None
