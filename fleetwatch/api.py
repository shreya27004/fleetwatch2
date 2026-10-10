"""Transport-independent request handling.

``handle`` is a pure function: (method, path, body bytes) -> (status, JSON).
It knows nothing about sockets, so tests call it directly and the HTTP server
in ``server.py`` stays a thin shell around it.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .errors import FleetError, ValidationError
from .registry import DeviceRegistry
from .validation import parse_heartbeat, parse_registration

Response = tuple[int, Any]


def _json_body(raw: bytes) -> Any:
    if not raw:
        raise ValidationError("request body is empty; expected a JSON object")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValidationError("request body is not valid JSON") from None


def handle(registry: DeviceRegistry, method: str, target: str, body: bytes = b"") -> Response:
    parts = urlsplit(target)
    segments = [unquote(s) for s in parts.path.strip("/").split("/") if s]
    query = parse_qs(parts.query)
    try:
        return _route(registry, method.upper(), segments, query, body)
    except FleetError as exc:
        return exc.http_status, {"error": str(exc)}


def _route(registry, method, seg, query, body) -> Response:
    if seg == ["health"] and method == "GET":
        return 200, {"ok": True}
    if seg == ["summary"] and method == "GET":
        return 200, registry.summary()
    if seg == ["devices"]:
        if method == "POST":
            device_id, name = parse_registration(_json_body(body))
            return 201, registry.register(device_id, name)
        if method == "GET":
            return 200, registry.list(status=query.get("status", [None])[0])
    elif len(seg) == 2 and seg[0] == "devices" and method == "GET":
        return 200, registry.get(seg[1])
    elif len(seg) == 3 and seg[0] == "devices" and seg[2] == "heartbeat" and method == "POST":
        beat = parse_heartbeat(_json_body(body))
        return 200, registry.heartbeat(seg[1], beat)

    known = seg in (["health"], ["summary"], ["devices"]) or (
        seg[:1] == ["devices"] and len(seg) in (2, 3)
    )
    if known:
        return 405, {"error": f"method {method} not allowed on /{'/'.join(seg)}"}
    return 404, {"error": f"no such endpoint: /{'/'.join(seg)}"}
