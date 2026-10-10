"""Plain data types shared by the registry and the API."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

ONLINE = "ONLINE"
OFFLINE = "OFFLINE"


@dataclass
class DeviceRecord:
    """Internal, mutable record. Only the registry touches it (under a lock)."""

    id: str
    name: str
    registered_at: datetime
    # When the *server* last heard from the device. Drives ONLINE/OFFLINE.
    last_seen: datetime | None = None
    # The timestamp the *device* reported (what operators see). Never goes backwards.
    last_heartbeat: datetime | None = None
    last_status: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    heartbeat_count: int = 0


@dataclass(frozen=True)
class Heartbeat:
    """A validated heartbeat. ``timestamp`` is None if the device omitted it."""

    status: str
    timestamp: datetime | None = None
    cpu_usage: float | None = None
    signal_strength: float | None = None
