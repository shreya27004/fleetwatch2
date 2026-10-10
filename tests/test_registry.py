"""Registration, heartbeat handling, status, and the 30-second rule.

All time-based tests use FakeClock, so nothing here sleeps.
"""
import threading
import unittest
from datetime import datetime, timezone

from fleetwatch.clock import FakeClock
from fleetwatch.errors import DeviceAlreadyExists, DeviceNotFound, ValidationError
from fleetwatch.models import Heartbeat
from fleetwatch.registry import DeviceRegistry

OK = Heartbeat(status="OK")


class RegistryTestCase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.registry = DeviceRegistry(clock=self.clock, timeout_seconds=30)


class RegistrationTests(RegistryTestCase):
    def test_register_returns_device_without_heartbeat(self):
        view = self.registry.register("device-01", "Lab Device 01")
        self.assertEqual(view["id"], "device-01")
        self.assertEqual(view["name"], "Lab Device 01")
        self.assertIsNone(view["last_heartbeat"])

    def test_duplicate_registration_rejected(self):
        self.registry.register("device-01", "A")
        with self.assertRaises(DeviceAlreadyExists):
            self.registry.register("device-01", "B")
        self.assertEqual(self.registry.get("device-01")["name"], "A")  # unchanged

    def test_unknown_device_lookup_raises(self):
        with self.assertRaises(DeviceNotFound):
            self.registry.get("ghost")


class HeartbeatTests(RegistryTestCase):
    def test_heartbeat_updates_last_heartbeat(self):
        self.registry.register("d1", "D1")
        ts = datetime(2026, 9, 21, 10, 29, 55, tzinfo=timezone.utc)
        self.registry.heartbeat("d1", Heartbeat(status="OK", timestamp=ts))
        self.assertEqual(self.registry.get("d1")["last_heartbeat"], "2026-09-21T10:29:55Z")

    def test_heartbeat_without_timestamp_uses_server_time(self):
        self.registry.register("d1", "D1")
        self.registry.heartbeat("d1", OK)
        self.assertEqual(self.registry.get("d1")["last_heartbeat"], "2026-09-21T10:30:00Z")

    def test_heartbeat_for_unregistered_device_raises(self):
        with self.assertRaises(DeviceNotFound):
            self.registry.heartbeat("ghost", OK)

    def test_out_of_order_heartbeat_does_not_move_time_backwards(self):
        self.registry.register("d1", "D1")
        new = datetime(2026, 9, 21, 10, 30, 0, tzinfo=timezone.utc)
        old = datetime(2026, 9, 21, 10, 0, 0, tzinfo=timezone.utc)
        self.registry.heartbeat("d1", Heartbeat(status="OK", timestamp=new))
        self.registry.heartbeat("d1", Heartbeat(status="OK", timestamp=old))
        detail = self.registry.get("d1")
        self.assertEqual(detail["last_heartbeat"], "2026-09-21T10:30:00Z")
        self.assertEqual(detail["heartbeat_count"], 2)  # still counted as contact

    def test_metrics_are_kept_and_survive_a_heartbeat_without_them(self):
        self.registry.register("d1", "D1")
        self.registry.heartbeat("d1", Heartbeat(status="OK", cpu_usage=42, signal_strength=-71))
        self.registry.heartbeat("d1", OK)
        self.assertEqual(self.registry.get("d1")["metrics"],
                         {"cpu_usage": 42.0, "signal_strength": -71.0})


class TimeoutTests(RegistryTestCase):
    def test_never_heard_from_is_offline(self):
        self.registry.register("d1", "D1")
        self.assertEqual(self.registry.get("d1")["status"], "OFFLINE")

    def test_online_right_after_heartbeat(self):
        self.registry.register("d1", "D1")
        self.registry.heartbeat("d1", OK)
        self.assertEqual(self.registry.get("d1")["status"], "ONLINE")

    def test_still_online_at_exactly_30_seconds(self):
        self.registry.register("d1", "D1")
        self.registry.heartbeat("d1", OK)
        self.clock.advance(30)
        self.assertEqual(self.registry.get("d1")["status"], "ONLINE")

    def test_offline_just_after_30_seconds(self):
        self.registry.register("d1", "D1")
        self.registry.heartbeat("d1", OK)
        self.clock.advance(30.001)
        self.assertEqual(self.registry.get("d1")["status"], "OFFLINE")

    def test_device_comes_back_online_after_new_heartbeat(self):
        self.registry.register("d1", "D1")
        self.registry.heartbeat("d1", OK)
        self.clock.advance(60)
        self.assertEqual(self.registry.get("d1")["status"], "OFFLINE")
        self.registry.heartbeat("d1", OK)
        self.assertEqual(self.registry.get("d1")["status"], "ONLINE")

    def test_stale_device_timestamp_does_not_make_device_offline(self):
        """Status uses server receive time, so a skewed device clock can't fool it."""
        self.registry.register("d1", "D1")
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        self.registry.heartbeat("d1", Heartbeat(status="OK", timestamp=old))
        self.assertEqual(self.registry.get("d1")["status"], "ONLINE")

    def test_timeout_is_configurable(self):
        registry = DeviceRegistry(clock=self.clock, timeout_seconds=5)
        registry.register("d1", "D1")
        registry.heartbeat("d1", OK)
        self.clock.advance(6)
        self.assertEqual(registry.get("d1")["status"], "OFFLINE")


class ListAndSummaryTests(RegistryTestCase):
    def _fleet(self):
        for i in range(1, 4):
            self.registry.register(f"d{i}", f"D{i}")
            self.registry.heartbeat(f"d{i}", OK)
        self.clock.advance(20)
        self.registry.heartbeat("d1", OK)   # refreshed
        self.registry.heartbeat("d2", OK)   # refreshed
        self.clock.advance(15)              # d3 silent for 35s; d1/d2 for 15s

    def test_summary_counts(self):
        self._fleet()
        self.assertEqual(self.registry.summary(), {"total": 3, "online": 2, "offline": 1})

    def test_summary_empty_fleet(self):
        self.assertEqual(self.registry.summary(), {"total": 0, "online": 0, "offline": 0})

    def test_list_is_sorted_and_reflects_status(self):
        self._fleet()
        listed = self.registry.list()
        self.assertEqual([d["id"] for d in listed], ["d1", "d2", "d3"])
        self.assertEqual([d["status"] for d in listed], ["ONLINE", "ONLINE", "OFFLINE"])

    def test_filter_by_status(self):
        self._fleet()
        self.assertEqual([d["id"] for d in self.registry.list(status="offline")], ["d3"])
        self.assertEqual(len(self.registry.list(status="ONLINE")), 2)

    def test_bad_status_filter_rejected(self):
        with self.assertRaises(ValidationError):
            self.registry.list(status="BROKEN")


class ConcurrencyTests(RegistryTestCase):
    def test_parallel_heartbeats_are_all_counted(self):
        self.registry.register("d1", "D1")

        def beat():
            for _ in range(200):
                self.registry.heartbeat("d1", OK)

        threads = [threading.Thread(target=beat) for _ in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(self.registry.get("d1")["heartbeat_count"], 1600)

    def test_parallel_registration_of_same_id_has_exactly_one_winner(self):
        results = []

        def attempt():
            try:
                self.registry.register("same", "X")
                results.append("ok")
            except DeviceAlreadyExists:
                results.append("dup")

        threads = [threading.Thread(target=attempt) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("dup"), 19)


if __name__ == "__main__":
    unittest.main()
