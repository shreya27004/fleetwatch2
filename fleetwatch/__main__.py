"""Run with:  python -m fleetwatch [--host H] [--port P] [--timeout S]"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import threading

from .registry import DEFAULT_TIMEOUT_SECONDS, DeviceRegistry
from .server import make_server


def main() -> None:
    env = os.environ.get
    parser = argparse.ArgumentParser(prog="fleetwatch", description="Device fleet monitor")
    parser.add_argument("--host", default=env("FLEETWATCH_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(env("FLEETWATCH_PORT", "8000")))
    parser.add_argument(
        "--timeout", type=float,
        default=float(env("FLEETWATCH_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
        help="seconds without a heartbeat before a device is OFFLINE (default 30)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = make_server(DeviceRegistry(timeout_seconds=args.timeout), args.host, args.port)

    # Graceful shutdown on Ctrl+C and SIGTERM (e.g. `docker stop`).
    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logging.info("FleetWatch listening on http://%s:%s (timeout %ss)",
                 args.host, args.port, args.timeout)
    server.serve_forever()
    server.server_close()
    logging.info("shut down cleanly")


if __name__ == "__main__":
    main()
