"""Helper utilities for normalizing and persisting Sunrise Coffee orders."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

BRAND_NAME = os.getenv("COFFEE_BRAND", "Sunrise Coffee")
_DEFAULT_ORDERS_DIR = Path(
    os.getenv("ORDERS_DIR", str(Path(__file__).resolve().parent.parent / "orders"))
)
_REQUIRED_FIELDS = ("drinkType", "size", "milk", "extras", "name")


def _clean_string(value: Any, field: str) -> str:
    if value is None:
        raise ValueError(f"Field '{field}' is required.")
    text = str(value).strip()
    if not text:
        raise ValueError(f"Field '{field}' cannot be empty.")
    return text


def _normalize_extras(extras: Any) -> list[str]:
    if extras is None:
        return []

    if isinstance(extras, str):
        candidates = [part.strip() for part in extras.split(",")]
    elif isinstance(extras, Sequence):
        candidates = []
        for item in extras:
            if isinstance(item, str):
                parts = item.split(",")
            else:
                parts = [str(item)]
            candidates.extend(part.strip() for part in parts)
    else:
        raise ValueError("Field 'extras' must be a string or list of strings.")

    cleaned: list[str] = []
    seen = set()
    for extra in candidates:
        if not extra:
            continue
        key = extra.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(extra)
    return cleaned


def normalize_order(order: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {}
    for field in ("drinkType", "size", "milk", "name"):
        normalized[field] = _clean_string(order.get(field), field)
    normalized["extras"] = _normalize_extras(order.get("extras"))

    # Ensure every required field is present
    missing = [field for field in _REQUIRED_FIELDS if field not in normalized]
    if missing:
        raise ValueError(f"Missing fields: {missing}")

    return normalized


def build_summary(order: Mapping[str, Any]) -> str:
    extras = order.get("extras", []) or []
    extras_phrase = f"extras: {', '.join(extras)}" if extras else "no extras"
    milk_value = str(order.get("milk", "")).strip()
    if not milk_value:
        milk_phrase = "with house milk"
    elif milk_value.lower().endswith("milk"):
        milk_phrase = f"with {milk_value}"
    else:
        milk_phrase = f"with {milk_value} milk"

    return (
        f"{BRAND_NAME} order for {order['name']}: "
        f"{order['size']} {order['drinkType']} {milk_phrase}, {extras_phrase}. "
        f"Ready for pickup under {order['name']}."
    )


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "guest"


def save_order_to_disk(order: Mapping[str, Any], directory: str | Path | None = None) -> dict[str, Any]:
    normalized = normalize_order(order)
    summary = build_summary(normalized)

    dir_path = Path(directory) if directory else _DEFAULT_ORDERS_DIR
    dir_path.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    filename = dir_path / f"{timestamp}_order_{_slugify(normalized['name'])}.json"

    payload = {
        "brand": BRAND_NAME,
        "order": normalized,
        "summary": summary,
        "savedAt": now.isoformat(),
    }

    filename.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {"path": str(filename), "summary": summary, "order": normalized}


__all__ = ["BRAND_NAME", "save_order_to_disk", "build_summary", "normalize_order"]
