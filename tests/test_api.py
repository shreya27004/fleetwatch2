"""API behaviour: status codes, payload shapes, validation and error handling.

Calls ``api.handle`` directly (no sockets) with a FakeClock.
"""
import json
import unittest

from fleetwatch.api import handle
from fleetwatch.clock import FakeClock
from fleetwatch.registry import DeviceRegistry


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.registry = DeviceRegistry(clock=self.clock)

    def call(self, method, path, body=None):
        raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        return handle(self.registry, method, path, raw)

    def register(self, device_id="device-01", name="Lab Device 01"):
        return self.call("POST", "/devices", {"id": device_id, "name": name})

    def beat(self, device_id="device-01", **extra):
        return self.call("POST", f"/devices/{device_id}/heartbeat",
                         {"timestamp": "2026-09-21T10:30:00Z", "status": "OK", **extra})


class RegisterApiTests(ApiTestCase):
    def test_register_returns_201(self):
        status, body = self.register()
        self.assertEqual(status, 201)
        self.assertEqual(body["id"], "device-01")
        self.assertEqual(body["status"], "OFFLINE")

    def test_duplicate_returns_409(self):
        self.register()
        status, body = self.register()
        self.assertEqual(status, 409)
        self.assertIn("already registered", body["error"])

    def test_validation_errors_return_400(self):
        bad_bodies = [
            {}, {"id": "x"}, {"name": "x"},
            {"id": "", "name": "x"}, {"id": "has space", "name": "x"},
            {"id": "../etc", "name": "x"}, {"id": "ok", "name": "   "},
            {"id": 5, "name": "x"}, [], "just a string",
        ]
        for bad in bad_bodies:
            with self.subTest(body=bad):
                self.assertEqual(self.call("POST", "/devices", bad)[0], 400)

    def test_malformed_json_returns_400(self):
        self.assertEqual(self.call("POST", "/devices", b"{not json")[0], 400)

    def test_empty_body_returns_400(self):
        self.assertEqual(handle(self.registry, "POST", "/devices", b"")[0], 400)


class HeartbeatApiTests(ApiTestCase):
    def test_heartbeat_makes_device_online(self):
        self.register()
        status, body = self.beat()
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ONLINE")
        self.assertEqual(body["last_heartbeat"], "2026-09-21T10:30:00Z")

    def test_heartbeat_for_unknown_device_returns_404(self):
        self.assertEqual(self.beat("ghost")[0], 404)

    def test_extra_fields_are_accepted_and_shown_in_details(self):
        self.register()
        self.beat(cpu_usage=42, signal_strength=-71)
        _, detail = self.call("GET", "/devices/device-01")
        self.assertEqual(detail["metrics"], {"cpu_usage": 42.0, "signal_strength": -71.0})

    def test_invalid_heartbeats_return_400(self):
        self.register()
        bad_bodies = [
            {}, {"status": ""}, {"status": 1},
            {"status": "OK", "timestamp": "yesterday"},
            {"status": "OK", "timestamp": 12345},
            {"status": "OK", "cpu_usage": "high"},
            {"status": "OK", "cpu_usage": 250},
            {"status": "OK", "cpu_usage": True},
            {"status": "OK", "signal_strength": 10},
        ]
        for bad in bad_bodies:
            with self.subTest(body=bad):
                self.assertEqual(self.call("POST", "/devices/device-01/heartbeat", bad)[0], 400)

    def test_timestamp_without_timezone_is_treated_as_utc(self):
        self.register()
        status, body = self.call("POST", "/devices/device-01/heartbeat",
                                 {"status": "OK", "timestamp": "2026-09-21T10:30:00"})
        self.assertEqual(status, 200)
        self.assertEqual(body["last_heartbeat"], "2026-09-21T10:30:00Z")

    def test_timestamp_with_offset_is_converted_to_utc(self):
        self.register()
        _, body = self.call("POST", "/devices/device-01/heartbeat",
                            {"status": "OK", "timestamp": "2026-09-21T16:00:00+05:30"})
        self.assertEqual(body["last_heartbeat"], "2026-09-21T10:30:00Z")


class QueryApiTests(ApiTestCase):
    def test_get_device_details(self):
        self.register()
        self.beat()
        status, body = self.call("GET", "/devices/device-01")
        self.assertEqual(status, 200)
        self.assertEqual(body["name"], "Lab Device 01")
        self.assertEqual(body["status"], "ONLINE")
        self.assertEqual(body["heartbeat_count"], 1)

    def test_get_unknown_device_returns_404(self):
        self.assertEqual(self.call("GET", "/devices/ghost")[0], 404)

    def test_list_matches_documented_shape(self):
        self.register()
        self.beat()
        status, body = self.call("GET", "/devices")
        self.assertEqual(status, 200)
        self.assertEqual(body, [{"id": "device-01", "name": "Lab Device 01",
                                 "status": "ONLINE", "last_heartbeat": "2026-09-21T10:30:00Z"}])

    def test_list_filter_and_bad_filter(self):
        self.register("a", "A"); self.register("b", "B"); self.beat("a")
        self.assertEqual([d["id"] for d in self.call("GET", "/devices?status=OFFLINE")[1]], ["b"])
        self.assertEqual(self.call("GET", "/devices?status=nope")[0], 400)

    def test_status_flips_to_offline_through_the_api(self):
        self.register()
        self.beat()
        self.clock.advance(31)
        self.assertEqual(self.call("GET", "/devices/device-01")[1]["status"], "OFFLINE")
        self.assertEqual(self.call("GET", "/summary")[1], {"total": 1, "online": 0, "offline": 1})

    def test_summary(self):
        for i in range(10):
            self.register(f"d{i}", f"D{i}")
        for i in range(8):
            self.beat(f"d{i}")
        self.assertEqual(self.call("GET", "/summary")[1], {"total": 10, "online": 8, "offline": 2})


class RoutingTests(ApiTestCase):
    def test_unknown_path_is_404(self):
        self.assertEqual(self.call("GET", "/nope")[0], 404)

    def test_wrong_method_is_405(self):
        self.assertEqual(self.call("DELETE", "/devices")[0], 405)
        self.assertEqual(self.call("GET", "/devices/x/heartbeat")[0], 405)
        self.assertEqual(self.call("POST", "/summary")[0], 405)

    def test_trailing_slash_and_health(self):
        self.assertEqual(self.call("GET", "/devices/")[0], 200)
        self.assertEqual(self.call("GET", "/health"), (200, {"ok": True}))


if __name__ == "__main__":
    unittest.main()
