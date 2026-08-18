import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import simulator_gui


class DatasetApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.app_data = Path(self.tempdir.name) / "app"
        self.datasets = Path(self.tempdir.name) / "datasets"
        simulator_gui.set_data_dir(str(self.app_data))
        self.client = simulator_gui.app.test_client()

    def tearDown(self):
        simulator_gui.reset_runtime_state()
        simulator_gui.set_data_dir(str(ROOT))
        self.tempdir.cleanup()

    def test_user_can_switch_directory_create_and_page_datasets(self):
        switched = self.client.post(
            "/api/dataset-directory/switch", json={"path": str(self.datasets)}
        )
        self.assertEqual(200, switched.status_code, switched.get_json())

        created = self.client.post(
            "/api/datasets",
            json={
                "id": "normal-device",
                "name": "正常设备",
                "description": "全量用例共享的正常态数据",
                "server": {"username": "admin", "password": "secret"},
                "rest_server": {"bind_address": "127.0.0.1", "port": 8080},
                "commands": [{"name": "show health", "output": "Normal"}],
                "rest_routes": [],
            },
        )
        self.assertEqual(201, created.status_code, created.get_json())
        self.assertTrue((self.datasets / "normal-device.json").is_file())

        response = self.client.get("/api/datasets?page=1&page_size=10&keyword=正常")
        self.assertEqual(200, response.status_code)
        result = response.get_json()
        self.assertEqual(1, result["total"])
        self.assertEqual("normal-device", result["items"][0]["id"])
        self.assertEqual(1, result["items"][0]["revision"])

        stored = json.loads(
            (self.datasets / "normal-device.json").read_text(encoding="utf-8")
        )
        self.assertEqual("normal-device", stored["id"])
        self.assertEqual("Normal", stored["commands"][0]["output"])
        self.assertNotIn("server", stored)
        self.assertNotIn("rest_server", stored)

    def test_global_service_settings_are_persisted_without_losing_dataset_directory(self):
        self.client.post("/api/dataset-directory/switch", json={"path": str(self.datasets)})

        response = self.client.put("/api/settings", json={
            "ssh_server": {"bind_address": "127.0.0.1", "port": 2222,
                           "username": "admin", "password": "admin123"},
            "rest_server": {"bind_address": "127.0.0.1", "port": 18080},
            "lease_timeout_seconds": 900,
        })

        self.assertEqual(200, response.status_code, response.get_json())
        reloaded = self.client.get("/api/settings").get_json()
        self.assertEqual({"bind_address": "127.0.0.1", "port": 18080},
                         reloaded["rest_server"])
        self.assertEqual({"bind_address": "127.0.0.1", "port": 2222,
                          "username": "admin", "password": "admin123"},
                         reloaded["ssh_server"])
        self.assertEqual(str(self.datasets.resolve()), reloaded["dataset_directory"])

    def test_dataset_update_requires_current_revision(self):
        self.client.post("/api/dataset-directory/switch", json={"path": str(self.datasets)})
        self.client.post("/api/datasets", json={"id": "alarm", "name": "告警", "commands": []})

        current = self.client.get("/api/datasets/alarm").get_json()
        current["description"] = "first update"
        updated = self.client.put("/api/datasets/alarm", json=current)
        self.assertEqual(200, updated.status_code, updated.get_json())
        self.assertEqual(2, updated.get_json()["revision"])

        current["description"] = "stale update"
        conflict = self.client.put("/api/datasets/alarm", json=current)
        self.assertEqual(409, conflict.status_code)
        self.assertEqual("first update", self.client.get("/api/datasets/alarm").get_json()["description"])

    def test_dataset_name_can_be_updated_without_changing_file_id(self):
        self.client.post("/api/dataset-directory/switch", json={"path": str(self.datasets)})
        self.client.post("/api/datasets", json={"id": "normal", "name": "Old name"})

        current = self.client.get("/api/datasets/normal").get_json()
        current["name"] = "New name"
        response = self.client.put("/api/datasets/normal", json=current)

        self.assertEqual(200, response.status_code, response.get_json())
        self.assertEqual("New name", response.get_json()["name"])
        self.assertEqual("normal", response.get_json()["id"])
        self.assertTrue((self.datasets / "normal.json").is_file())

    def test_case_catalog_is_paged_and_case_can_be_rebound(self):
        self.client.post("/api/dataset-directory/switch", json={"path": str(self.datasets)})
        for dataset_id in ("normal", "alarm"):
            self.client.post("/api/datasets", json={"id": dataset_id, "commands": []})
        cases = [{"case_id": f"TC.Storage.{index:04d}", "name": f"存储用例 {index}",
                  "module": "storage"} for index in range(55)]
        synced = self.client.post("/api/cases/sync", json={"cases": cases})
        self.assertEqual(200, synced.status_code, synced.get_json())

        page = self.client.get("/api/cases?page=3&page_size=20&keyword=存储").get_json()
        self.assertEqual(55, page["total"])
        self.assertEqual(15, len(page["items"]))

        case_id = "TC.Storage.0001"
        first = self.client.put(f"/api/bindings/{case_id}", json={"dataset_id": "normal"})
        second = self.client.put(f"/api/bindings/{case_id}", json={"dataset_id": "alarm"})
        self.assertEqual(200, first.status_code, first.get_json())
        self.assertEqual(200, second.status_code, second.get_json())
        bindings = self.client.get("/api/bindings?page=1&page_size=20").get_json()
        self.assertEqual(1, bindings["total"])
        self.assertEqual("alarm", bindings["items"][0]["dataset_id"])

    def test_activation_is_exclusive_and_keeps_an_immutable_snapshot(self):
        self.client.post("/api/dataset-directory/switch", json={"path": str(self.datasets)})
        created = self.client.post("/api/datasets", json={
            "id": "normal", "commands": [{"name": "show health", "output": "Normal"}],
            "rest_routes": []}).get_json()
        self.client.put("/api/bindings/TC.Storage.0001", json={"dataset_id": "normal"})

        activated = self.client.post("/api/runtime/activate-case", json={
            "case_id": "TC.Storage.0001", "execution_id": "run-1"})
        self.assertEqual(200, activated.status_code, activated.get_json())
        self.assertEqual("normal.json", activated.get_json()["dataset_file"])
        self.assertTrue(activated.get_json()["checksum"].startswith("sha256:"))

        busy = self.client.post("/api/runtime/activate-case", json={
            "case_id": "TC.Storage.0001", "execution_id": "run-2"})
        self.assertEqual(409, busy.status_code)

        created["commands"][0]["output"] = "Changed"
        self.client.put("/api/datasets/normal", json=created)
        status = self.client.get("/api/runtime/status").get_json()
        self.assertEqual(1, status["dataset_revision"])
        self.assertNotIn("snapshot", status)

        wrong_owner = self.client.post("/api/runtime/release", json={"execution_id": "run-2"})
        self.assertEqual(409, wrong_owner.status_code)
        released = self.client.post("/api/runtime/release", json={"execution_id": "run-1"})
        self.assertEqual(200, released.status_code)
        self.assertEqual("idle", self.client.get("/api/runtime/status").get_json()["status"])

    def test_legacy_config_is_migrated_once_without_overwriting_dataset_files(self):
        legacy = {"server": {"username": "legacy"},
                  "commands": [{"name": "show legacy", "output": "legacy output"}]}
        self.app_data.mkdir(parents=True, exist_ok=True)
        (self.app_data / "config.json").write_text(json.dumps(legacy), encoding="utf-8")

        first = self.client.get("/api/dataset-directory").get_json()
        self.assertEqual(1, first["dataset_count"])
        migrated = self.client.get("/api/datasets/legacy-default").get_json()
        self.assertEqual("legacy output", migrated["commands"][0]["output"])
        self.assertNotIn("server", migrated)
        self.assertNotIn("rest_server", migrated)

        migrated["commands"][0]["output"] = "user edit"
        self.client.put("/api/datasets/legacy-default", json=migrated)
        self.client.get("/api/dataset-directory")
        self.assertEqual("user edit", self.client.get("/api/datasets/legacy-default").get_json()["commands"][0]["output"])

    def test_legacy_dataset_config_fields_are_stripped_from_file(self):
        self.client.post("/api/dataset-directory/switch", json={"path": str(self.datasets)})
        path = self.datasets / "legacy.json"
        raw = {"id": "legacy", "name": "旧格式", "revision": 2,
               "server": {"bind_address": "0.0.0.0", "port": 22,
                          "username": "admin", "password": "old"},
               "rest_server": {"bind_address": "0.0.0.0", "port": 443},
               "commands": [{"name": "show", "output": "ok"}], "rest_routes": []}
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

        loaded = self.client.get("/api/datasets/legacy").get_json()
        self.assertNotIn("server", loaded)
        self.assertNotIn("rest_server", loaded)

        stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("server", stored)
        self.assertNotIn("rest_server", stored)

    def test_dataset_copy_import_export_and_bulk_binding_are_supported(self):
        self.client.post("/api/dataset-directory/switch", json={"path": str(self.datasets)})
        self.client.post("/api/datasets", json={"id": "source", "commands": [{"name": "x", "output": "y"}]})
        copied = self.client.post("/api/datasets/source/copy", json={"id": "copy", "name": "副本"})
        self.assertEqual(201, copied.status_code, copied.get_json())
        self.assertEqual("y", copied.get_json()["commands"][0]["output"])

        exported = self.client.get("/api/datasets/copy/export")
        self.assertEqual(200, exported.status_code)
        self.assertIn("attachment", exported.headers["Content-Disposition"])
        exported.close()

        imported = self.client.post("/api/datasets/import", json={"dataset": {
            "id": "imported", "name": "导入", "commands": [], "rest_routes": []}})
        self.assertEqual(201, imported.status_code, imported.get_json())
        bulk = self.client.post("/api/bindings/import", json={"bindings": [
            {"case_id": "TC.1", "dataset_id": "source"},
            {"case_id": "TC.2", "dataset_id": "imported"}]})
        self.assertEqual(200, bulk.status_code, bulk.get_json())
        self.assertEqual(2, self.client.get("/api/bindings?page=1&page_size=20").get_json()["total"])

    def test_workbench_can_manually_activate_selected_dataset(self):
        self.client.post("/api/dataset-directory/switch", json={"path": str(self.datasets)})
        self.client.post("/api/datasets", json={"id": "manual", "commands": [], "rest_routes": []})

        response = self.client.post("/api/runtime/activate-dataset", json={
            "dataset_id": "manual", "execution_id": "manual-ui-1"})

        self.assertEqual(200, response.status_code, response.get_json())
        self.assertEqual("manual", response.get_json()["dataset_id"])
        self.assertEqual("manual-ui-1", response.get_json()["execution_id"])

    def test_log_import_duplicate_check_is_scoped_to_selected_dataset(self):
        self.client.post("/api/dataset-directory/switch", json={"path": str(self.datasets)})
        self.client.post("/api/datasets", json={"id": "logs", "commands": [], "rest_routes": [
            {"method": "GET", "uri": "/redfish/v1/Systems", "status_code": 200,
             "response_headers": {}, "response_body": "{}"}]})
        log_text = """2026 [INFO] ##url : /redfish/v1/Systems ##method : GET [thread-1]
2026 [INFO] ##result : {\"ok\":true} [thread-1]"""

        response = self.client.post("/api/rest/import-log/preview", json={
            "dataset_id": "logs", "log_text": log_text})

        self.assertEqual(200, response.status_code)
        self.assertEqual("duplicate", response.get_json()["routes"][0]["status"])

    def test_ssh_log_preview_extracts_commands_and_cleans_terminal_output(self):
        self.client.post("/api/dataset-directory/switch", json={"path": str(self.datasets)})
        self.client.post("/api/datasets", json={"id": "ssh-logs", "commands": []})
        log_text = r"""2026-08-17 19:22:34:495 [INFO] Execute command line : show system general, timeout is : 30 (SshConnection.java:873) [login_device_pool-4-thread-2](pid-25320)
2026-08-17 19:22:34:639 [INFO] Receive str : show system general
System Name         : OceanStor_24A.Storage
Health Status       : Normal
smartkit:/> (SshConnection.java:1513) [login_device_pool-4-thread-2](pid-25320)
2026-08-17 19:22:34:647 [INFO] Execute command line : show system general|filterColumn exclude columnList=Product\sModel, timeout is : 30 (SshConnection.java:873) [login_device_pool-4-thread-2](pid-25320)
2026-08-17 19:22:34:774 [INFO] Receive str : show system general|filterColumn exclude columnList=Product\sModel
Unknown command: show system general|filterColumn exclude columnList=Product\sModel
Type 'help' for available commands.
smartkit:/> (SshConnection.java:1513) [login_device_pool-4-thread-2](pid-25320)
2026-08-17 19:22:34:845 [INFO] Execute command line : show user user_name=admin, timeout is : 30 (SshConnection.java:873) [login_device_pool-4-thread-2](pid-25320)
2026-08-17 19:22:34:959 [INFO] Receive str : show user user_name=admin
Unknown command: show user user_name=admin
Type 'help' for available commands."""

        response = self.client.post("/api/ssh/import-log/preview", json={
            "dataset_id": "ssh-logs", "log_text": log_text})

        self.assertEqual(200, response.status_code, response.get_json())
        payload = response.get_json()
        self.assertEqual({"total": 3, "importable": 3, "duplicate": 0, "incomplete": 0},
                         payload["summary"])
        commands = [entry["command"] for entry in payload["commands"]]
        self.assertEqual("show system general", commands[0]["name"])
        self.assertIn("System Name", commands[0]["output"])
        self.assertNotIn("show system general\n", commands[0]["output"])
        self.assertNotIn("smartkit:/>", commands[0]["output"])
        self.assertNotIn("SshConnection.java", commands[0]["output"])
        self.assertEqual(r"show system general|filterColumn exclude columnList=Product\sModel",
                         commands[1]["name"])
        self.assertIn("Unknown command", commands[1]["output"])
        self.assertIn("Unknown command", commands[2]["output"])

    def test_ssh_log_preview_pairs_threads_and_marks_duplicates_and_incomplete(self):
        self.client.post("/api/dataset-directory/switch", json={"path": str(self.datasets)})
        self.client.post("/api/datasets", json={"id": "ssh-edge", "commands": [
            {"name": "existing", "description": "", "output": "old"}]})
        log_text = """2026-08-17 19:00:00:001 [INFO] Execute command line : alpha, timeout is : 30 [thread-a](pid-1)
2026-08-17 19:00:00:002 [INFO] Execute command line : beta, timeout is : 30 [thread-b](pid-2)
2026-08-17 19:00:00:003 [INFO] Receive str : beta
beta-output
device:/> (SshConnection.java:1513) [thread-b](pid-2)
2026-08-17 19:00:00:004 [INFO] Receive str : alpha
alpha-output
device:/> (SshConnection.java:1513) [thread-a](pid-1)
2026-08-17 19:00:00:005 [INFO] Execute command line : existing, timeout is : 30 [thread-a](pid-1)
2026-08-17 19:00:00:006 [INFO] Receive str : existing
new-output
device:/> (SshConnection.java:1513) [thread-a](pid-1)
2026-08-17 19:00:00:007 [INFO] Execute command line : alpha, timeout is : 30 [thread-a](pid-1)
2026-08-17 19:00:00:008 [INFO] Receive str : alpha
second-alpha
device:/> (SshConnection.java:1513) [thread-a](pid-1)
2026-08-17 19:00:00:009 [INFO] Execute command line : orphan, timeout is : 30 [thread-a](pid-1)"""

        payload = self.client.post("/api/ssh/import-log/preview", json={
            "dataset_id": "ssh-edge", "log_text": log_text}).get_json()

        self.assertEqual({"total": 5, "importable": 2, "duplicate": 2, "incomplete": 1},
                         payload["summary"])
        by_name = {entry["command"]["name"]: entry for entry in payload["commands"]}
        self.assertEqual("alpha-output", payload["commands"][0]["command"]["output"])
        self.assertEqual("beta-output", by_name["beta"]["command"]["output"])
        self.assertEqual("duplicate", by_name["existing"]["status"])
        self.assertEqual("missing_response", by_name["orphan"]["status"])

    def test_ssh_log_preview_validates_log_and_dataset(self):
        empty = self.client.post("/api/ssh/import-log/preview", json={"log_text": ""})
        missing = self.client.post("/api/ssh/import-log/preview", json={
            "dataset_id": "missing", "log_text": "2026 [INFO] Execute command line : x, timeout is : 1"})

        self.assertEqual(400, empty.status_code)
        self.assertEqual(404, missing.status_code)


if __name__ == "__main__":
    unittest.main()
