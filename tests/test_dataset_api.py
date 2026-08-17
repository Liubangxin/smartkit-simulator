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

        migrated["commands"][0]["output"] = "user edit"
        self.client.put("/api/datasets/legacy-default", json=migrated)
        self.client.get("/api/dataset-directory")
        self.assertEqual("user edit", self.client.get("/api/datasets/legacy-default").get_json()["commands"][0]["output"])

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


if __name__ == "__main__":
    unittest.main()
