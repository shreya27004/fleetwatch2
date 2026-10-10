#!/usr/bin/env python3
"""Device simulator + live fleet view for FleetWatch (standard library only).

Starts N simulated devices that each send a heartbeat every few seconds, and
redraws a live table of the fleet as seen by the server. Stop a device to watch
it flip to OFFLINE after the timeout; start it again to watch it recover.

    python simulator/simulate.py                       # 5 devices, every 5s
    python simulator/simulate.py --kill device-03 --kill-after 10
    # interactive commands while running:  stop device-02 | start device-02 | quit
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def call(base: str, method: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


class SimulatedDevice(threading.Thread):
    """Sends heartbeats until stopped. Can be stopped and started again."""

    def __init__(self, base: str, device_id: str, interval: float):
        super().__init__(daemon=True)
        self.base, self.device_id, self.interval = base, device_id, interval
        self._alive = threading.Event()   # set => device is "powered on"
        self._quit = threading.Event()
        self._alive.set()

    def power(self, on: bool) -> None:
        self._alive.set() if on else self._alive.clear()

    def shutdown(self) -> None:
        self._quit.set()

    def run(self) -> None:
        while not self._quit.is_set():
            if self._alive.is_set():
                try:
                    call(self.base, "POST", f"/devices/{self.device_id}/heartbeat", {
                        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "status": "OK",
                        "cpu_usage": random.randint(10, 90),
                        "signal_strength": random.randint(-90, -50),
                    })
                except OSError:
                    pass  # server briefly unreachable: keep trying, like a real device
            self._quit.wait(self.interval)


def render(base: str, powered: dict[str, bool]) -> None:
    try:
        _, devices = call(base, "GET", "/devices")
        _, summary = call(base, "GET", "/summary")
    except OSError as exc:
        print(f"\033[2J\033[Hcannot reach {base}: {exc}")
        return
    lines = [f"\033[2J\033[HFleetWatch @ {base}   "
             f"total={summary['total']} online={summary['online']} offline={summary['offline']}",
             "", f"{'ID':<12} {'NAME':<18} {'STATUS':<9} {'SIM':<5} LAST HEARTBEAT"]
    for d in devices:
        colour = GREEN if d["status"] == "ONLINE" else RED
        sim = "on" if powered.get(d["id"], True) else "OFF"
        lines.append(f"{d['id']:<12} {d['name']:<18} {colour}{d['status']:<9}{RESET} "
                     f"{sim:<5} {DIM}{d['last_heartbeat'] or '-'}{RESET}")
    lines += ["", "commands: stop <id> | start <id> | quit"]
    print("\n".join(lines), flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--url", default="http://127.0.0.1:8000")
    p.add_argument("--devices", type=int, default=5)
    p.add_argument("--interval", type=float, default=5.0, help="seconds between heartbeats")
    p.add_argument("--kill", metavar="ID", help="stop this device automatically")
    p.add_argument("--kill-after", type=float, default=15.0, help="seconds before --kill")
    p.add_argument("--no-ui", action="store_true", help="don't redraw the live table")
    args = p.parse_args()

    ids = [f"device-{i:02d}" for i in range(1, args.devices + 1)]
    for i, dev_id in enumerate(ids, 1):
        status, body = call(args.url, "POST", "/devices", {"id": dev_id, "name": f"Lab Device {i:02d}"})
        if status not in (201, 409):  # 409 = already registered on a previous run: fine
            print(f"could not register {dev_id}: {status} {body}", file=sys.stderr)
            return 1

    devices = {i: SimulatedDevice(args.url, i, args.interval) for i in ids}
    for d in devices.values():
        d.start()
    powered = {i: True for i in ids}
    done = threading.Event()

    def set_power(dev_id: str, on: bool) -> None:
        if dev_id in devices:
            devices[dev_id].power(on)
            powered[dev_id] = on

    if args.kill:
        threading.Timer(args.kill_after, set_power, (args.kill, False)).start()

    def ui_loop() -> None:
        while not done.is_set():
            render(args.url, powered)
            done.wait(2)

    if not args.no_ui:
        threading.Thread(target=ui_loop, daemon=True).start()
    else:
        print(f"{len(ids)} devices heartbeating every {args.interval}s. Commands: stop <id> | start <id> | quit")

    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            cmd, *rest = line.split()
            if cmd == "quit":
                break
            if cmd in ("stop", "start") and rest:
                set_power(rest[0], cmd == "start")
    except KeyboardInterrupt:
        pass
    # stdin closed (e.g. run in background): keep running until Ctrl+C
    if not sys.stdin.isatty():
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    done.set()
    for d in devices.values():
        d.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
