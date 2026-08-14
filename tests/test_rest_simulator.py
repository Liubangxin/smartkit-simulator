import json
import socket
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import simulator_gui


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class RestSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.original = simulator_gui.load_config()
        self.port = free_port()
        config = dict(self.original)
        config["rest_server"] = {"bind_address": "127.0.0.1", "port": self.port}
        config["rest_routes"] = [{
            "method": "GET", "uri": "/api/device/info", "status_code": 201,
            "response_headers": {"Content-Type": "application/json", "X-Simulator": "SmartKit"},
            "response_body": '{"status":"normal"}',
        }, {
            "method": "POST", "uri": "/api/device/info", "status_code": 204,
            "response_headers": {}, "response_body": "",
        }]
        simulator_gui.save_config(config)
        response = simulator_gui.app.test_client().post(
            "/api/rest/start", json={"bind_address": "127.0.0.1", "port": self.port})
        self.assertEqual(200, response.status_code)
        time.sleep(0.1)

    def tearDown(self):
        simulator_gui.stop_rest_server_thread()
        simulator_gui.save_config(self.original)

    def request(self, path, method="GET"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        return urllib.request.urlopen(req, timeout=5)

    def test_returns_configured_status_headers_and_body(self):
        with self.request("/api/device/info") as response:
            self.assertEqual(201, response.status)
            self.assertEqual("SmartKit", response.headers["X-Simulator"])
            self.assertEqual({"status": "normal"}, json.load(response))

    def test_same_uri_is_distinguished_by_http_method(self):
        with self.request("/api/device/info", "POST") as response:
            self.assertEqual(204, response.status)

    def test_unknown_method_and_uri_return_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/device/info", "DELETE")
        self.assertEqual(404, caught.exception.code)

    def test_routes_are_hot_reloaded_from_config(self):
        config = simulator_gui.load_config()
        config["rest_routes"][0]["response_body"] = '{"status":"changed"}'
        simulator_gui.save_config(config)
        with self.request("/api/device/info") as response:
            self.assertEqual({"status": "changed"}, json.load(response))

    def test_config_normalizes_explicit_and_legacy_groups(self):
        config = {
            "commands": [{"name": "show", "group": "System", "output": "ok"}],
            "command_groups": ["Empty", "System", "Empty"],
            "rest_routes": [{"method": "GET", "uri": "/x", "group": "Device"}],
            "rest_groups": [],
        }
        normalized = simulator_gui.normalize_groups(config)
        self.assertEqual(["Empty", "System"], normalized["command_groups"])
        self.assertEqual(["Device"], normalized["rest_groups"])


if __name__ == "__main__":
    unittest.main()
