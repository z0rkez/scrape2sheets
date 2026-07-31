"""CLI: парсинг сайтов из конфига -> нормализация -> Google Sheets.

    python -m scrape2sheets.pipeline --config config.yaml
    python -m scrape2sheets.pipeline --config config.yaml --dry-run --out data.csv
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

import pandas as pd
import yaml

from .scrape import Scraper, SiteConfig

log = logging.getLogger("scrape2sheets")


def load_config(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def normalize(rows: list[dict[str, Any]], columns: list[str]) -> pd.DataFrame:
    """Единая схема колонок, обрезка пробелов, дедупликация по ключу."""
    df = pd.DataFrame(rows)
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    df = df[columns]
    for col in columns:
        df[col] = df[col].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    return df


def run(cfg: dict[str, Any], *, dry_run: bool, out_csv: str | None) -> int:
    scraper = Scraper(proxy=cfg.get("proxy"))

    rows: list[dict[str, Any]] = []
    for site in cfg["sites"]:
        try:
            rows.extend(scraper.crawl(SiteConfig(**site)))
        except Exception as exc:  # noqa: BLE001 — один сайт не роняет остальные
            log.error("сайт %s пропущен: %s", site.get("name"), exc)

    if not rows:
        log.error("не собрано ни одной строки")
        return 1

    enrich_cfg = cfg.get("enrich") or {}
    if enrich_cfg.get("enabled"):
        from .enrich import enrich_rows

        rows = enrich_rows(
            rows,
            enrich_cfg["instruction"],
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            batch_size=enrich_cfg.get("batch_size", 25),
        )

    df = normalize(rows, cfg["columns"])
    key = cfg.get("dedup_key")
    if key:
        before = len(df)
        df = df.drop_duplicates(subset=key)
        log.info("дедупликация по %s: %d -> %d", key, before, len(df))

    log.info("итого строк: %d", len(df))

    if out_csv:
        df.to_csv(out_csv, index=False, encoding="utf-8-sig")
        log.info("CSV: %s", out_csv)

    if dry_run:
        log.info("--dry-run: запись в Google Sheets пропущена")
        return 0

    from .sheets import get_worksheet, open_sheet, write_rows

    gs = cfg["google_sheets"]
    sheet = open_sheet(gs["credentials"], gs["spreadsheet_id"])
    ws = get_worksheet(sheet, gs.get("worksheet", "data"), cols=len(df.columns))
    written = write_rows(
        ws,
        list(df.columns),
        df.values.tolist(),
        batch_size=gs.get("batch_size", 500),
        mode=gs.get("mode", "replace"),
    )
    log.info("в таблицу записано строк: %d", written)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Парсинг сайтов -> Google Sheets")
    ap.add_argument("--config", required=True)
    ap.add_argument("--dry-run", action="store_true", help="не писать в таблицу")
    ap.add_argument("--out", help="дополнительно сохранить CSV")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    return run(load_config(args.config), dry_run=args.dry_run, out_csv=args.out)


if __name__ == "__main__":
    sys.exit(main())
