"""Необязательный шаг: обогащение спарсенных строк через Claude API.

Категоризация, нормализация, извлечение атрибутов из свободного текста —
то, что регуляркой не берётся. Батчами, чтобы не платить за строку.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from anthropic import Anthropic

log = logging.getLogger(__name__)

MODEL = "claude-opus-5"

SYSTEM = (
    "Ты обрабатываешь строки таблицы, полученные парсингом сайтов. "
    "На вход — JSON-массив объектов. Для каждого объекта верни объект с полями, "
    "перечисленными в задании. Отвечай ТОЛЬКО JSON-массивом той же длины и в том же "
    "порядке, без markdown-обёртки и пояснений."
)


def _extract_text(message: Any) -> str:
    """У adaptive thinking в content лежат и thinking-блоки — берём только текст."""
    return "".join(b.text for b in message.content if b.type == "text").strip()


def _parse_json_array(raw: str, expected: int) -> list[dict[str, Any]]:
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"в ответе нет JSON-массива: {raw[:200]}")
    data = json.loads(raw[start : end + 1])
    if len(data) != expected:
        raise ValueError(f"ожидалось {expected} объектов, пришло {len(data)}")
    return data


def enrich_rows(
    rows: Sequence[dict[str, Any]],
    instruction: str,
    *,
    api_key: str | None = None,
    batch_size: int = 25,
    max_tokens: int = 8000,
) -> list[dict[str, Any]]:
    """Прогоняет строки через Claude батчами, дописывает полученные поля к исходным.

    instruction — что именно извлечь/посчитать, задаётся в конфиге под задачу.
    Если батч не удалось разобрать, строки уходят дальше без обогащения:
    пайплайн не должен падать целиком из-за одного батча.
    """
    client = Anthropic(api_key=api_key) if api_key else Anthropic()
    out: list[dict[str, Any]] = []

    for i in range(0, len(rows), batch_size):
        batch = list(rows[i : i + batch_size])
        prompt = (
            f"{instruction}\n\nВходные данные:\n"
            f"{json.dumps(batch, ensure_ascii=False, indent=1)}"
        )
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=max_tokens,
                thinking={"type": "adaptive"},
                system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                message = stream.get_final_message()
            enriched = _parse_json_array(_extract_text(message), len(batch))
            out.extend({**src, **add} for src, add in zip(batch, enriched))
            log.info("обогащено %d/%d строк", len(out), len(rows))
        except Exception as exc:  # noqa: BLE001 — батч не должен ронять весь прогон
            log.warning("батч %d пропущен без обогащения: %s", i // batch_size + 1, exc)
            out.extend(batch)

    return out
