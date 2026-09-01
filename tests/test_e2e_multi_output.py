"""End-to-end test for the ordered multi-output SSH command feature.

Boots the real backend as a headless subprocess, drives it exclusively
through the management HTTP API, and exercises the SSH simulator over a
real TCP connection with paramiko:

* dataset creation with ``outputs`` + schema normalization (mirror / 400)
* activation, then round-robin output sequences on a single connection
* per-connection isolation (a new connection starts from the first output)
* legacy single-output and unknown-command behavior
* log import: repeated commands merged into ordered ``outputs`` (missing
  responses become empty placeholders), then served by the simulator
"""

import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
BACKEND = ROOT / "simulator_gui.py"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http_json(url, method="GET", payload=None, timeout=10):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        try:
            body = json.load(error)
        except Exception:
            body = {}
        return error.code, body


class MultiOutputEndToEndTests(unittest.TestCase):
    USERNAME = "admin"
    PASSWORD = "admin123"

    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.data_dir = Path(cls.tempdir.name) / "app"
        cls.datasets_dir = Path(cls.tempdir.name) / "datasets"
        cls.port = free_port()
        cls.proc = subprocess.Popen(
            [PYTHON, str(BACKEND), "--headless",
             "--management-port", str(cls.port),
             "--data-dir", str(cls.data_dir)],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        cls.base = f"http://127.0.0.1:{cls.port}"
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                status, _ = http_json(cls.base + "/api/runtime/health", timeout=2)
                if status == 200:
                    break
            except Exception:
                time.sleep(0.3)
        else:
            cls.proc.terminate()
            raise RuntimeError("backend did not become ready")
        status, result = http_json(cls.base + "/api/dataset-directory/switch", "POST",
                                   {"path": str(cls.datasets_dir)})
        assert status == 200, result

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.tempdir.cleanup()

    # ------------------------------------------------------------------ helpers

    def create_dataset(self, dataset_id, commands):
        status, result = http_json(self.base + "/api/datasets", "POST", {
            "id": dataset_id, "name": dataset_id, "commands": commands, "rest_routes": []})
        self.assertEqual(201, status, result)
        return result

    def activate(self, dataset_id, execution_id):
        status, result = http_json(self.base + "/api/runtime/activate-dataset", "POST", {
            "dataset_id": dataset_id, "execution_id": execution_id})
        self.assertEqual(200, status, result)

    def release(self, execution_id):
        status, result = http_json(self.base + "/api/runtime/release", "POST",
                                   {"execution_id": execution_id})
        self.assertEqual(200, status, result)

    def start_ssh(self, port):
        status, result = http_json(self.base + "/api/server/start", "POST", {"port": port})
        self.assertEqual(200, status, result)

    def stop_ssh(self):
        http_json(self.base + "/api/server/stop", "POST")

    def execs_on_connection(self, ssh_port, commands):
        """One real SSH connection; run each command and return stripped outputs."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                "127.0.0.1", port=ssh_port,
                username=self.USERNAME, password=self.PASSWORD,
                look_for_keys=False, allow_agent=False, timeout=10,
            )
            outputs = []
            for command in commands:
                _stdin, stdout, stderr = client.exec_command(command, timeout=10)
                self.assertEqual("", stderr.read().decode("utf-8", errors="replace"))
                outputs.append(stdout.read().decode("utf-8", errors="replace").strip())
            return outputs
        finally:
            client.close()

    # -------------------------------------------------------------------- tests

    def test_multi_output_round_robin_connection_isolation_and_legacy_compat(self):
        ssh_port = free_port()
        execution = "e2e-run-1"
        try:
            self.create_dataset("multi-e2e", [
                {"name": "show alarm", "description": "",
                 "outputs": ["Alarm A", "Alarm B", "Alarm C"]},
                {"name": "show version", "description": "", "output": "V1.0"},
            ])
            self.activate("multi-e2e", execution)
            self.start_ssh(ssh_port)

            # One connection advances round-robin through the ordered outputs.
            self.assertEqual(["Alarm A", "Alarm B", "Alarm C", "Alarm A"],
                             self.execs_on_connection(ssh_port, ["show alarm"] * 4))
            # A new connection starts from the first output (per-connection isolation).
            self.assertEqual(["Alarm A", "Alarm B"],
                             self.execs_on_connection(ssh_port, ["show alarm", "show alarm"]))
            # Legacy single-output command keeps repeating the same output.
            self.assertEqual(["V1.0", "V1.0"],
                             self.execs_on_connection(ssh_port, ["show version", "show version"]))
            # Unknown commands are unchanged.
            self.assertEqual(["Unknown command: nope"],
                             self.execs_on_connection(ssh_port, ["nope"]))
        finally:
            self.stop_ssh()
            self.release(execution)

    def test_log_import_merges_repeated_commands_and_serves_the_sequence(self):
        execution = "e2e-run-2"
        ssh_port = free_port()
        log_text = """2026-08-17 19:00:00:001 [INFO] Execute command line : show alarm, timeout is : 30 (SshConnection.java:873) [thread-a](pid-1)
2026-08-17 19:00:00:002 [INFO] Receive str : show alarm
show alarm
Critical alarm detected
smartkit:/> (SshConnection.java:1513) [thread-a](pid-1)
2026-08-17 19:00:00:003 [INFO] Execute command line : show alarm, timeout is : 30 (SshConnection.java:873) [thread-a](pid-1)
2026-08-17 19:00:00:004 [INFO] Receive str : show alarm
show alarm
No alarm
smartkit:/> (SshConnection.java:1513) [thread-a](pid-1)
2026-08-17 19:00:00:005 [INFO] Execute command line : show alarm, timeout is : 30 (SshConnection.java:873) [thread-a](pid-1)
2026-08-17 19:00:00:006 [INFO] Execute command line : show disk, timeout is : 30 (SshConnection.java:873) [thread-a](pid-1)
2026-08-17 19:00:00:007 [INFO] Receive str : show disk
show disk
Disk OK
smartkit:/> (SshConnection.java:1513) [thread-a](pid-1)"""
        try:
            self.create_dataset("import-e2e", [])
            # Preview: show alarm appears 3 times (2 responses, 1 missing) -> merged
            # into one entry with an empty placeholder; show disk is a new command.
            status, preview = http_json(self.base + "/api/ssh/import-log/preview", "POST", {
                "dataset_id": "import-e2e", "log_text": log_text})
            self.assertEqual(200, status)
            self.assertEqual({"total": 2, "importable": 2, "duplicate": 0, "incomplete": 1},
                             preview["summary"])
            by_name = {entry["command"]["name"]: entry for entry in preview["commands"]}
            self.assertEqual(["Critical alarm detected", "No alarm", ""],
                             by_name["show alarm"]["command"]["outputs"])
            self.assertEqual("ready", by_name["show disk"]["status"])

            # Confirm import exactly like the workbench does: merge ready commands.
            status, detail = http_json(self.base + "/api/datasets/import-e2e", "GET")
            self.assertEqual(200, status)
            for entry in preview["commands"]:
                if entry["status"] == "ready":
                    detail["commands"].append(dict(entry["command"]))
            status, saved = http_json(self.base + "/api/datasets/import-e2e", "PUT", detail)
            self.assertEqual(200, status, saved)
            imported = {command["name"]: command for command in saved["commands"]}
            self.assertEqual(["Critical alarm detected", "No alarm", ""],
                             imported["show alarm"]["outputs"])
            self.assertEqual("Critical alarm detected", imported["show alarm"]["output"])
            self.assertEqual("Disk OK", imported["show disk"]["output"])

            # Activate the imported dataset and serve the sequence over SSH.
            self.activate("import-e2e", execution)
            self.start_ssh(ssh_port)
            self.assertEqual(["Critical alarm detected", "No alarm", "", "Critical alarm detected"],
                             self.execs_on_connection(ssh_port, ["show alarm"] * 4))
        finally:
            self.stop_ssh()
            self.release(execution)

    def test_dataset_schema_normalization_over_http(self):
        created = self.create_dataset("schema-e2e", [
            {"name": "multi", "outputs": ["x", "y", "z"]},
            {"name": "empty", "outputs": []},
            {"name": "legacy", "output": "only"},
        ])
        by_name = {command["name"]: command for command in created["commands"]}
        self.assertEqual(["x", "y", "z"], by_name["multi"]["outputs"])
        self.assertEqual("x", by_name["multi"]["output"])          # mirrored
        self.assertNotIn("outputs", by_name["empty"])              # dropped
        self.assertNotIn("outputs", by_name["legacy"])             # untouched

        status, result = http_json(self.base + "/api/datasets", "POST", {
            "id": "bad-e2e", "name": "bad",
            "commands": [{"name": "x", "outputs": ["ok", 42]}], "rest_routes": []})
        self.assertEqual(400, status, result)


if __name__ == "__main__":
    unittest.main()
