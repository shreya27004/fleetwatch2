# FleetWatch: Mini Device Fleet Monitor

FleetWatch tracks a fleet of devices that send periodic heartbeats. An operator can
register devices, see which are ONLINE or OFFLINE, and get a fleet summary
over a small JSON HTTP API. A device is ONLINE if it has been heard from within the
last 30 seconds (configurable), otherwise OFFLINE.

It uses only the Python standard library, so there is nothing to install.

## Design / architecture

```
fleetwatch/
├── __main__.py     entry point: CLI args / env vars, graceful shutdown
├── server.py       thin HTTP shell (ThreadingHTTPServer): bytes in, bytes out
├── api.py          routing + status codes; pure function, no sockets
├── validation.py   untrusted JSON -> validated values (or ValidationError)
├── registry.py     DeviceRegistry: state, locking, and the ONLINE/OFFLINE rule
├── models.py       dataclasses (DeviceRecord, Heartbeat)
├── clock.py        SystemClock + FakeClock (injectable time)
└── errors.py       domain errors, each carrying its HTTP status
```

Key decisions:

1. Status is derived, not stored. The registry stores `last_seen` and computes
   ONLINE/OFFLINE from the clock every time it answers. There is no background
   "sweeper" thread, nothing can go stale, and every response is correct at the moment
   it is produced.
2. Injectable clock. The registry asks a `Clock` for the time. Tests use `FakeClock`
   and jump 31 seconds forward instantly, so the 30-second behaviour is tested
   precisely (including the exact 30.0s boundary) without sleeping.
3. Transport-independent API layer. `api.handle(registry, method, path, body)` is a
   pure function. Most tests call it directly; one end-to-end test uses a real socket.
4. One lock, small critical sections. All registry mutations and reads take a single
   `threading.Lock`, so the threaded HTTP server is safe (covered by concurrency tests).
5. Domain errors map to HTTP codes (400 / 404 / 409), so the registry has no HTTP
   knowledge and the API has no `if/else` ladders.

## Prerequisites

Python 3.10+ (developed on 3.12). No third-party packages.

## Build

Nothing to build. Clone and run:

```bash
git clone <https://github.com/shreya27004/fleetwatch2> && cd <repo>
```

## Run the application

```bash
python -m fleetwatch                      # http://127.0.0.1:8000
python -m fleetwatch --port 9000 --timeout 30
```

Configuration (flags override env vars):

| Env var | Flag | Default |
|---|---|---|
| `FLEETWATCH_HOST` | `--host` | `127.0.0.1` |
| `FLEETWATCH_PORT` | `--port` | `8000` |
| `FLEETWATCH_TIMEOUT_SECONDS` | `--timeout` | `30` |

Stop with Ctrl+C or SIGTERM; the server shuts down cleanly.

## Run the simulator

In a second terminal, with the server running:

```bash
python simulator/simulate.py
```

This registers `device-01` to `device-05`, sends a heartbeat from each every 5 seconds, and
shows a live, colour-coded table of the fleet as the server sees it. To watch a device go OFFLINE:

```bash
# type into the simulator terminal:
stop device-03        # after ~30s it turns OFFLINE
start device-03       # it recovers on its next heartbeat
quit

# or automatic:
python simulator/simulate.py --kill device-03 --kill-after 10
```

Other options: `--devices N`, `--interval SECONDS`, `--url URL`, `--no-ui`.
Tip: run the server with `--timeout 10` for a quicker demo.

## Run the tests

```bash
python -m unittest discover -s tests -t . -v
```

43 tests; they run in under a second. They cover registration, heartbeat handling,
status, the 30s rule (exactly 30s / 30.001s / recovery / skewed device clock),
validation, error codes, routing, concurrency, and one real-socket end-to-end flow.

## Example API requests

```bash
# Register
curl -X POST localhost:8000/devices -d '{"id":"device-01","name":"Lab Device 01"}'

# Heartbeat (extra fields optional)
curl -X POST localhost:8000/devices/device-01/heartbeat \
  -d '{"timestamp":"2026-09-21T10:30:00Z","status":"OK","cpu_usage":42,"signal_strength":-71}'

curl localhost:8000/devices                      # list (add ?status=OFFLINE to filter)
curl localhost:8000/devices/device-01            # details incl. metrics, heartbeat_count
curl localhost:8000/summary                      # {"total":10,"online":8,"offline":2}
curl localhost:8000/health
```

| Situation | Response |
|---|---|
| Register OK | `201` |
| Heartbeat OK / reads | `200` |
| Invalid JSON / fields / bad filter | `400` + `{"error": "..."}` |
| Unknown device | `404` |
| Duplicate device id | `409` |
| Wrong method on a real path | `405` |

## Assumptions

- ONLINE/OFFLINE uses the server's receive time, not the device-reported timestamp,
  because device clocks drift. The device `timestamp` is stored and shown as
  `last_heartbeat`; it never moves backwards if packets arrive out of order.
- "Within the last 30 seconds" is inclusive: exactly 30.0s is still ONLINE.
- A registered device that has never sent a heartbeat is OFFLINE with `last_heartbeat: null`.
- `timestamp` is optional (defaults to server time); one without a timezone is treated as UTC.
- `status` is any non-empty string up to 32 chars, stored upper-cased.
- Optional metrics: `cpu_usage` 0-100, `signal_strength` -150 to 0.
- Re-registering an existing id is a 409, not an upsert.

## Known limitations

- State is in memory; restarting the server forgets all devices.
- Single process, single lock. Fine for hundreds of devices, not millions.
- No authentication: any caller can send a heartbeat for any device.
- `ThreadingHTTPServer` is simple, not high-performance; no TLS.
- No device deletion/update endpoint.

## What I'd improve with one more day

- SQLite persistence (the registry is the only thing to swap; the API doesn't change).
- Per-device auth tokens issued at registration.
- Status-change history/events (when did a device go offline, and for how long).
- Pagination for `GET /devices`; OpenAPI spec.
- Dockerfile and a CI workflow running the tests.

## AI Usage


- Tools used: Claude and Perplexity
- What I used them for: Doing documentation, explanations, debugging, syntax help, and writing the README file.
- One thing I verified myself: Debugging the simulate and models files further after changes suggested.
