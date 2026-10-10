"""One end-to-end test over a real socket, to prove the HTTP shell is wired up."""
import json
import threading
import unittest
import urllib.error
import urllib.request

from fleetwatch.registry import DeviceRegistry
from fleetwatch.server import make_server


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(DeviceRegistry(), "127.0.0.1", 0)  # port 0 = any free port
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_full_flow_over_http(self):
        self.assertEqual(self.request("POST", "/devices", {"id": "e2e", "name": "E2E"})[0], 201)
        self.assertEqual(self.request("GET", "/devices/e2e")[1]["status"], "OFFLINE")
        status, body = self.request("POST", "/devices/e2e/heartbeat",
                                    {"timestamp": "2026-09-21T10:30:00Z", "status": "OK"})
        self.assertEqual((status, body["status"]), (200, "ONLINE"))
        self.assertEqual(self.request("GET", "/summary")[1]["online"], 1)
        self.assertEqual(self.request("GET", "/devices/missing")[0], 404)


if __name__ == "__main__":
    unittest.main()
