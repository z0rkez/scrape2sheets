"""Запись в Google Sheets через gspread: батчинг, ретраи на 429/5xx, дозапись."""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Iterable, Sequence

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

# Квота Sheets API: 60 запросов в минуту на пользователя на проект.
# Ретраим только то, что имеет смысл ретраить.
RETRYABLE = {429, 500, 502, 503, 504}


def open_sheet(credentials_path: str, spreadsheet_id: str) -> gspread.Spreadsheet:
    creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    return gspread.authorize(creds).open_by_key(spreadsheet_id)


def get_worksheet(
    sheet: gspread.Spreadsheet, title: str, cols: int
) -> gspread.Worksheet:
    try:
        return sheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return sheet.add_worksheet(title=title, rows=1000, cols=max(cols, 10))


def _with_retries(fn, *args, attempts: int = 6, **kwargs) -> Any:
    """Экспоненциальный бэкофф с джиттером. 429 от Sheets — норма, не ошибка."""
    delay = 1.0
    for attempt in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except APIError as exc:
            code = exc.response.status_code
            if code not in RETRYABLE or attempt == attempts:
                raise
            sleep = delay + random.uniform(0, delay * 0.3)
            log.warning(
                "Sheets API %s, попытка %d/%d, пауза %.1f с", code, attempt, attempts, sleep
            )
            time.sleep(sleep)
            delay = min(delay * 2, 64.0)
    raise RuntimeError("недостижимо")


def _chunks(rows: Sequence[Sequence[Any]], size: int) -> Iterable[list[list[Any]]]:
    for i in range(0, len(rows), size):
        yield [list(r) for r in rows[i : i + size]]


def write_rows(
    ws: gspread.Worksheet,
    header: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    batch_size: int = 500,
    mode: str = "replace",
) -> int:
    """Пишет строки батчами. mode: replace — очистить лист, append — дописать.

    Возвращает количество записанных строк.
    """
    if mode not in ("replace", "append"):
        raise ValueError(f"неизвестный режим: {mode}")

    if mode == "replace":
        _with_retries(ws.clear)
        _with_retries(ws.update, [list(header)], "A1", value_input_option="RAW")
    elif not _with_retries(ws.get_values, "A1:A1"):
        _with_retries(ws.update, [list(header)], "A1", value_input_option="RAW")

    written = 0
    for batch in _chunks(rows, batch_size):
        _with_retries(ws.append_rows, batch, value_input_option="RAW")
        written += len(batch)
        log.info("записано %d/%d строк", written, len(rows))
    return written
