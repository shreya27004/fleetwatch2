"""Turn untrusted JSON into validated objects, or raise ValidationError."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .errors import ValidationError
from .models import Heartbeat

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _require_object(body: Any) -> dict:
    if not isinstance(body, dict):
        raise ValidationError("request body must be a JSON object")
    return body


def parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValidationError("'timestamp' must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError(f"'timestamp' is not valid ISO-8601: {value!r}") from None
    if parsed.tzinfo is None:  # assume UTC if the device didn't say
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_registration(body: Any) -> tuple[str, str]:
    body = _require_object(body)
    device_id, name = body.get("id"), body.get("name")
    if not isinstance(device_id, str) or not _ID_RE.match(device_id):
        raise ValidationError(
            "'id' is required: 1-64 chars, letters/digits/'.'/'_'/'-', starting alphanumeric"
        )
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValidationError("'name' is required: a non-empty string up to 100 chars")
    return device_id, name.strip()


def _number(body: dict, key: str, lo: float, hi: float) -> float | None:
    if key not in body or body[key] is None:
        return None
    value = body[key]
    # bool is a subclass of int in Python; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"'{key}' must be a number")
    if not lo <= value <= hi:
        raise ValidationError(f"'{key}' must be between {lo} and {hi}")
    return float(value)


def parse_heartbeat(body: Any) -> Heartbeat:
    body = _require_object(body)
    status = body.get("status")
    if not isinstance(status, str) or not status.strip() or len(status) > 32:
        raise ValidationError("'status' is required: a non-empty string up to 32 chars")
    timestamp = parse_timestamp(body["timestamp"]) if body.get("timestamp") is not None else None
    return Heartbeat(
        status=status.strip().upper(),
        timestamp=timestamp,
        cpu_usage=_number(body, "cpu_usage", 0, 100),
        signal_strength=_number(body, "signal_strength", -150, 0),
    )
