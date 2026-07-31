# scrape2sheets

Пайплайн: **парсинг сайтов → нормализация → автозапись в Google Sheets через API.**

Селекторы и настройки живут в YAML — под новый сайт код менять не нужно.

```
парсинг (requests + BeautifulSoup)
   → нормализация и дедупликация (pandas)
   → опционально: обогащение через Claude API
   → запись в Google Sheets (gspread, Service Account, батчами)
```

## Что внутри

| Модуль | Отвечает за |
|---|---|
| `scrape2sheets/scrape.py` | HTTP с ретраями и бэкоффом, пагинация, прокси, определение кодировки |
| `scrape2sheets/sheets.py` | gspread + Service Account, батчинг записи, обработка лимитов 429/5xx |
| `scrape2sheets/enrich.py` | обогащение данных через Claude API (необязательный шаг) |
| `scrape2sheets/pipeline.py` | CLI, единая схема колонок, дедупликация, `--dry-run` |

## Быстрый старт

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp config.example.yaml config.yaml
python -m scrape2sheets.pipeline --config config.yaml --dry-run --out data.csv
```

`--dry-run` собирает данные и кладёт в CSV, не трогая таблицу — удобно проверять селекторы.

Боевой прогон:

```bash
python -m scrape2sheets.pipeline --config config.yaml
```

## Демонстрация

Конфиг из коробки собирает 3 страницы каталога `books.toscrape.com`:

```
INFO [books] страница 1: https://books.toscrape.com/catalogue/page-1.html
INFO [books] найдено карточек: 20
INFO [books] страница 2: ...
INFO дедупликация по url: 60 -> 60
INFO итого строк: 60
INFO CSV: demo_output.csv
```

Результат — [`demo_output.csv`](demo_output.csv), 60 строк.

## Настройка Google Sheets

1. В Google Cloud Console создать проект, включить **Google Sheets API**.
2. Создать **Service Account**, скачать JSON-ключ → положить рядом как `service_account.json`.
3. Открыть таблицу и дать доступ **на редактирование** почте сервис-аккаунта (`...@....iam.gserviceaccount.com`).
4. `spreadsheet_id` — часть URL между `/d/` и `/edit`.

Ключ и `config.yaml` в `.gitignore` — секреты в репозиторий не попадают.

## Как добавить сайт

Правится только YAML:

```yaml
sites:
  - name: shop
    start_url: "https://example.com/catalog?page=1"
    item_selector: "div.product-card"     # карточка товара
    fields:                                # колонка -> CSS-селектор внутри карточки
      title: "a.product-title"
      price: "span.price"
      url:   "a.product-title"
    attrs:                                 # взять атрибут вместо текста
      url: href                            # href разворачивается в абсолютный URL
    next_selector: "a.pagination-next"     # пагинация; убрать — одна страница
    max_pages: 50
    delay: 1.0                             # пауза между страницами, сек

columns: [_source, title, price, url]
dedup_key: url
```

Сайтов в списке может быть несколько — падение одного не роняет прогон остальных.

## Обработка лимитов и ошибок

- Google Sheets API — 60 запросов в минуту на пользователя. Запись идёт батчами по 500 строк, на `429` и `5xx` — экспоненциальный бэкофф с джиттером до 6 попыток.
- Парсер ретраит `429/5xx` и сетевые сбои, бэкофф до 30 секунд.
- Ошибка на одном сайте или одном батче логируется, остальные продолжают работу.
- `mode: append` дописывает строки, `mode: replace` перезаписывает лист.

## Динамические сайты

Модуль `scrape.py` рассчитан на статику. Для JS-рендеринга подменяется только `Scraper.fetch` — на Playwright или Selenium; остальной пайплайн не меняется. Прокси задаётся ключом `proxy` в конфиге.

## Обогащение через Claude API

Необязательный шаг между парсингом и записью: категоризация, нормализация, извлечение атрибутов из свободного текста.

```yaml
enrich:
  enabled: true
  batch_size: 25
  instruction: |
    Для каждого объекта верни поля:
      price_num — цена числом без валюты,
      genre     — жанр книги одним словом по названию.
```

Ключ берётся из переменной окружения `ANTHROPIC_API_KEY`. Строки идут батчами, неразобранный батч проходит дальше без обогащения — прогон не падает целиком.

## Тесты

```bash
python tests/test_pipeline.py
```

Разбор HTML, абсолютные URL, пагинация и нормализация проверяются без сети.
