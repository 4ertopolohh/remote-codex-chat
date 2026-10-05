"""Project app-server rate limits into safe application data."""

from __future__ import annotations

from math import isfinite
from typing import Any


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) else None


def _window(value: Any) -> dict[str, int | float] | None:
    if not isinstance(value, dict):
        return None
    fields = {
        "used_percent": _number(value.get("usedPercent")),
        "window_duration_mins": _number(value.get("windowDurationMins")),
        "resets_at": _number(value.get("resetsAt")),
    }
    return {key: field for key, field in fields.items() if field is not None} or None


def _snapshot(value: Any) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, object] = {}
    if isinstance(value.get("limitId"), str) and value["limitId"]:
        result["limit_id"] = value["limitId"]
    if isinstance(value.get("limitName"), str) and value["limitName"]:
        result["limit_name"] = value["limitName"]
    for key in ("primary", "secondary"):
        window = _window(value.get(key))
        if window is not None:
            result[key] = window
    return result or None


def normalize_usage(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        return {"status": "error", "rate_limits": None, "rate_limits_by_id": {}, "ordinary_usage_allowed": None}
    raw_by_id = value.get("rateLimitsByLimitId")
    by_id = {
        key: normalized
        for key, item in raw_by_id.items()
        if isinstance(key, str) and (normalized := _snapshot(item)) is not None
    } if isinstance(raw_by_id, dict) else {}
    allowed = value.get("ordinaryUsageAllowed")
    return {
        "status": "available",
        "rate_limits": _snapshot(value.get("rateLimits")),
        "rate_limits_by_id": by_id,
        "ordinary_usage_allowed": allowed if isinstance(allowed, bool) else None,
    }


def normalize_usage_update(value: Any) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return _snapshot(value.get("rateLimits"))
