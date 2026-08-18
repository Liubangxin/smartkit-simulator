import json
import socket
import ssl
import sys
import tempfile
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
        self.tempdir = tempfile.TemporaryDirectory()
        simulator_gui.set_data_dir(self.tempdir.name)
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
        }, {
            "method": "GET", "uri": "/redfish/v1/Sessions/{session_id}", "status_code": 200,
            "response_headers": {"Location": "/redfish/v1/Sessions/{session_id}"},
            "response_body": '{"id":"{session_id}"}',
        }, {
            "method": "GET", "uri": "/redfish/v1/Sessions/current", "status_code": 200,
            "response_headers": {}, "response_body": '{"kind":"exact"}',
        }]
        simulator_gui.save_config(config)
        response = simulator_gui.app.test_client().post(
            "/api/rest/start", json={"bind_address": "127.0.0.1", "port": self.port})
        self.assertEqual(200, response.status_code)
        self.start_result = response.get_json()
        time.sleep(0.1)

    def tearDown(self):
        simulator_gui.stop_rest_server_thread()
        simulator_gui.reset_runtime_state()
        simulator_gui.set_data_dir(str(ROOT))
        simulator_gui.save_config(self.original)
        self.tempdir.cleanup()

    def request(self, path, method="GET"):
        req = urllib.request.Request(f"https://127.0.0.1:{self.port}{path}", method=method)
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        return urllib.request.urlopen(req, timeout=5, context=context)

    def test_returns_configured_status_headers_and_body(self):
        with self.request("/api/device/info") as response:
            self.assertEqual(201, response.status)
            self.assertEqual("SmartKit", response.headers["X-Simulator"])
            self.assertEqual({"status": "normal"}, json.load(response))

    def test_start_response_includes_real_access_url(self):
        self.assertEqual([f"https://127.0.0.1:{self.port}"], self.start_result["access_urls"])
        self.assertEqual(["TLSv1.2", "TLSv1.3"], self.start_result["tls_versions"])

    def test_server_negotiates_tls_1_3(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname="localhost") as tls:
                self.assertEqual("TLSv1.3", tls.version())

    def test_server_negotiates_tls_1_2(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname="localhost") as tls:
                self.assertEqual("TLSv1.2", tls.version())

    def test_same_uri_is_distinguished_by_http_method(self):
        with self.request("/api/device/info", "POST") as response:
            self.assertEqual(204, response.status)

    def test_api_tester_returns_status_headers_body_timing_and_tls(self):
        response = simulator_gui.app.test_client().post("/api/rest/test", json={
            "method": "GET",
            "url": f"https://127.0.0.1:{self.port}/api/device/info",
            "headers": {"Accept": "application/json"},
            "body": "",
        })
        self.assertEqual(200, response.status_code)
        result = response.get_json()
        self.assertEqual("ok", result["status"])
        self.assertEqual(201, result["status_code"])
        self.assertEqual("TLSv1.3", result["tls_version"])
        self.assertGreaterEqual(result["elapsed_ms"], 0)
        self.assertIn("normal", result["response_body"])
        self.assertTrue(any(name == "X-Simulator" for name, _value in result["response_headers"]))

    def test_api_tester_rejects_invalid_url(self):
        response = simulator_gui.app.test_client().post("/api/rest/test", json={
            "method": "GET", "url": "file:///tmp/test", "headers": {}, "body": "",
        })
        self.assertEqual(400, response.status_code)

    def test_unknown_method_and_uri_return_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/device/info", "DELETE")
        self.assertEqual(404, caught.exception.code)

    def test_named_path_parameter_is_substituted_in_headers_and_body(self):
        with self.request("/redfish/v1/Sessions/abc-123") as response:
            self.assertEqual("/redfish/v1/Sessions/abc-123", response.headers["Location"])
            self.assertEqual({"id": "abc-123"}, json.load(response))

    def test_exact_route_takes_priority_over_parameter_route(self):
        with self.request("/redfish/v1/Sessions/current") as response:
            self.assertEqual({"kind": "exact"}, json.load(response))

    def test_routes_are_hot_reloaded_from_config(self):
        config = simulator_gui.load_config()
        config["rest_routes"][0]["response_body"] = '{"status":"changed"}'
        simulator_gui.save_config(config)
        with self.request("/api/device/info") as response:
            self.assertEqual({"status": "changed"}, json.load(response))

    def test_running_protocol_uses_activated_immutable_dataset_snapshot(self):
        client = simulator_gui.app.test_client()
        datasets = Path(self.tempdir.name) / "datasets"
        client.post("/api/dataset-directory/switch", json={"path": str(datasets)})
        created = client.post("/api/datasets", json={
            "id": "snapshot", "commands": [], "rest_routes": [{
                "method": "GET", "uri": "/snapshot", "status_code": 200,
                "response_headers": {"Content-Type": "application/json"},
                "response_body": '{"value":"before"}'
            }]}).get_json()
        client.put("/api/bindings/TC.Snapshot.001", json={"dataset_id": "snapshot"})
        activated = client.post("/api/runtime/activate-case", json={
            "case_id": "TC.Snapshot.001", "execution_id": "rest-run"})
        self.assertEqual(200, activated.status_code, activated.get_json())

        created["rest_routes"][0]["response_body"] = '{"value":"after"}'
        client.put("/api/datasets/snapshot", json=created)
        with self.request("/snapshot") as response:
            self.assertEqual({"value": "before"}, json.load(response))

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

    def test_log_import_extracts_multiline_json_and_reports_skipped_routes(self):
        log_text = """2026-08-15 15:42:05:685 [INFO] ##url : /redfish/v1/Chassis ##method : GET ##ip : 127.0.0.1 (RedfishConnestion.java:541) [http-nio-exec-9](pid-3240)
2026-08-15 15:42:05:700 [INFO] ##ip 127.0.0.1 ##result : {
  \"@odata.id\": \"/redfish/v1/Chassis\",
  \"Members\": [{\"@odata.id\": \"/redfish/v1/Chassis/1\"}]
} (RedfishConnestion.java:761) [http-nio-exec-9](pid-3240)
2026-08-15 15:42:05:702 [INFO] ##url : /api/device/info ##method : GET ##ip : 127.0.0.1 (RedfishConnestion.java:541) [http-nio-exec-10](pid-3240)
2026-08-15 15:42:05:703 [INFO] ##result : {\"status\":\"duplicate\"} (RedfishConnestion.java:761) [http-nio-exec-10](pid-3240)
2026-08-15 15:42:05:704 [INFO] ##url : /redfish/v1/Chassis/1 ##method : GET ##ip : 127.0.0.1 (RedfishConnestion.java:541) [http-nio-exec-9](pid-3240)"""

        response = simulator_gui.app.test_client().post(
            "/api/rest/import-log/preview", json={"log_text": log_text})

        self.assertEqual(200, response.status_code)
        result = response.get_json()
        self.assertEqual({"total": 3, "importable": 1, "duplicate": 1, "incomplete": 1}, result["summary"])
        self.assertEqual("ready", result["routes"][0]["status"])
        self.assertEqual("/redfish/v1/Chassis", result["routes"][0]["route"]["uri"])
        self.assertEqual("application/json", result["routes"][0]["route"]["response_headers"]["Content-Type"])
        self.assertEqual({"@odata.id": "/redfish/v1/Chassis", "Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]},
                         json.loads(result["routes"][0]["route"]["response_body"]))
        self.assertEqual("duplicate", result["routes"][1]["status"])
        self.assertEqual("missing_response", result["routes"][2]["status"])

    def test_log_import_uses_thread_to_match_interleaved_responses(self):
        log_text = """2026 [INFO] ##url : /one ##method : GET (A.java:1) [thread-1](pid-1)
2026 [INFO] ##url : /two ##method : POST (A.java:1) [thread-2](pid-1)
2026 [INFO] ##result : {\"value\":2} (A.java:2) [thread-2](pid-1)
2026 [INFO] ##result : {\"value\":1} (A.java:2) [thread-1](pid-1)"""

        routes = simulator_gui.parse_rest_routes_from_log(log_text)

        self.assertEqual({"value": 1}, json.loads(routes[0]["response_body"]))
        self.assertEqual({"value": 2}, json.loads(routes[1]["response_body"]))

    def test_log_import_extracts_http_session_sending_and_received_format(self):
        log_text = """2026-08-18 10:24:46:392 [INFO] Sending PUT request to https://127.0.0.1:443/rest/plat/smapp/v1/sessions ...  (HttpSession.java:606) [http-nio-exec-6](pid-25320)
2026-08-18 10:24:46:435 [INFO] Received PUT response successfully from https://127.0.0.1:443/rest/plat/smapp/v1/sessions. (HttpSession.java:611) [http-nio-exec-6](pid-25320)
2026-08-18 10:24:46:520 [INFO] Sending GET request to https://127.0.0.1:443/rest/productmgmt/v1/system-info ...  (HttpSession.java:606) [http-nio-exec-6](pid-25320)
2026-08-18 10:24:46:540 [INFO] Received GET response successfully from https://127.0.0.1:443/rest/productmgmt/v1/system-info. (HttpSession.java:611) [http-nio-exec-6](pid-25320)
2026-08-18 10:24:46:542 [INFO] ResponseInfo : {"a":"1"} (RestConnection.java:837) [http-nio-exec-6](pid-25320)"""

        routes = simulator_gui.parse_rest_routes_from_log(log_text)

        self.assertEqual([("PUT", "/rest/plat/smapp/v1/sessions"),
                          ("GET", "/rest/productmgmt/v1/system-info")],
                         [(route["method"], route["uri"]) for route in routes])
        self.assertEqual({}, json.loads(routes[0]["response_body"]))
        self.assertEqual({"a": "1"}, json.loads(routes[1]["response_body"]))
        self.assertEqual({"Content-Type": "application/json"}, routes[1]["response_headers"])

    def test_log_import_rejects_empty_text(self):
        response = simulator_gui.app.test_client().post(
            "/api/rest/import-log/preview", json={"log_text": "  "})
        self.assertEqual(400, response.status_code)


if __name__ == "__main__":
    unittest.main()
