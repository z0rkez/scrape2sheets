"""Тесты на разбор HTML и нормализацию — без сети."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scrape2sheets.pipeline import normalize  # noqa: E402
from scrape2sheets.scrape import Scraper, SiteConfig  # noqa: E402

HTML = """
<html><body>
  <article class="product_pod">
    <h3><a href="../catalogue/a_1/index.html" title="Полное название книги">Полное наз...</a></h3>
    <p class="price_color">£51.77</p>
    <p class="instock availability">  In stock  </p>
  </article>
  <article class="product_pod">
    <h3><a href="../catalogue/b_2/index.html" title="Вторая книга">Вторая...</a></h3>
    <p class="price_color">£12.00</p>
  </article>
  <li class="next"><a href="page-2.html">next</a></li>
</body></html>
"""

CFG = SiteConfig(
    name="books",
    start_url="https://example.com/catalogue/page-1.html",
    item_selector="article.product_pod",
    fields={"title": "h3 a", "price": "p.price_color", "availability": "p.instock.availability", "url": "h3 a"},
    attrs={"title": "title", "url": "href"},
    next_selector="li.next a",
)


def test_parse_page():
    rows = Scraper().parse_page(HTML, CFG, CFG.start_url)
    assert len(rows) == 2
    assert rows[0]["title"] == "Полное название книги"      # атрибут, а не обрезанный текст
    assert rows[0]["url"] == "https://example.com/catalogue/a_1/index.html"  # абсолютный URL
    assert rows[1]["availability"] == ""                     # отсутствующий блок не роняет парсер


def test_next_url():
    assert Scraper._next_url(HTML, CFG, CFG.start_url) == "https://example.com/catalogue/page-2.html"
    assert Scraper._next_url(HTML, SiteConfig("x", "u", "i", {}), "u") is None


def test_normalize_adds_missing_columns_and_trims():
    df = normalize([{"title": "  A\n  B ", "_source": "s"}], ["_source", "title", "price"])
    assert list(df.columns) == ["_source", "title", "price"]
    assert df.loc[0, "title"] == "A B"
    assert df.loc[0, "price"] == ""


if __name__ == "__main__":
    test_parse_page()
    test_next_url()
    test_normalize_adds_missing_columns_and_trims()
    print("все тесты прошли")
