"""The heart of the app: device state and the ONLINE/OFFLINE rule.

Design note: status is derived at read time from last_seen and the clock.
Nothing is stored as ONLINE/OFFLINE, so there is no background thread to
sweep devices, nothing can go stale, and every API answer is correct the
instant it is computed."""
from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any

from .clock import SystemClock
from .errors import DeviceAlreadyExists, DeviceNotFound, ValidationError
from .models import OFFLINE, ONLINE, DeviceRecord, Heartbeat
from .validation import format_timestamp

DEFAULT_TIMEOUT_SECONDS = 30.0


class DeviceRegistry:
    def __init__(self, clock=None, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._clock = clock or SystemClock()
        self._timeout = timedelta(seconds=timeout_seconds)
        self._devices: dict[str, DeviceRecord] = {}
        self._lock = threading.Lock()

    #commands
    def register(self, device_id: str, name: str) -> dict[str, Any]:
        with self._lock:
            if device_id in self._devices:
                raise DeviceAlreadyExists(f"device '{device_id}' is already registered")
            now = self._clock.now()
            record = DeviceRecord(id=device_id, name=name, registered_at=now)
            self._devices[device_id] = record
            return self._view(record, now)

    def heartbeat(self, device_id: str, beat: Heartbeat) -> dict[str, Any]:
        with self._lock:
            record = self._devices.get(device_id)
            if record is None:
                raise DeviceNotFound(f"device '{device_id}' is not registered")
            now = self._clock.now()
            record.last_seen = now
            record.last_status = beat.status
            record.heartbeat_count += 1
            reported = beat.timestamp or now
            # A late/out-of-order packet must not move the displayed time backwards.
            if record.last_heartbeat is None or reported > record.last_heartbeat:
                record.last_heartbeat = reported
            for key in ("cpu_usage", "signal_strength"):
                value = getattr(beat, key)
                if value is not None:
                    record.extras[key] = value
            return self._view(record, now)

    #queries
    def get(self, device_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._devices.get(device_id)
            if record is None:
                raise DeviceNotFound(f"device '{device_id}' is not registered")
            return self._view(record, self._clock.now(), detailed=True)

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        if status is not None:
            status = status.upper()
            if status not in (ONLINE, OFFLINE):
                raise ValidationError("'status' filter must be ONLINE or OFFLINE")
        with self._lock:
            now = self._clock.now()
            views = [self._view(r, now) for r in self._devices.values()]
        views.sort(key=lambda v: v["id"])
        return [v for v in views if status is None or v["status"] == status]

    def summary(self) -> dict[str, int]:
        with self._lock:
            now = self._clock.now()
            online = sum(1 for r in self._devices.values() if self._status(r, now) == ONLINE)
            total = len(self._devices)
        return {"total": total, "online": online, "offline": total - online}

    # internals 
    def _status(self, record: DeviceRecord, now) -> str:
        """ONLINE iff heard from within the timeout (exactly 30s still counts)."""
        if record.last_seen is None:
            return OFFLINE  # registered but never sent a heartbeat
        return ONLINE if now - record.last_seen <= self._timeout else OFFLINE

    def _view(self, record: DeviceRecord, now, detailed: bool = False) -> dict[str, Any]:
        view: dict[str, Any] = {
            "id": record.id,
            "name": record.name,
            "status": self._status(record, now),
            "last_heartbeat": format_timestamp(record.last_heartbeat),
        }
        if detailed:
            view.update(
                registered_at=format_timestamp(record.registered_at),
                last_seen=format_timestamp(record.last_seen),
                last_reported_status=record.last_status,
                heartbeat_count=record.heartbeat_count,
                metrics=dict(record.extras),
                timeout_seconds=self._timeout.total_seconds(),
            )
        return view
