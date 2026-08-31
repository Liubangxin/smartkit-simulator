import socket
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import simulator_gui


def free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class SimulatorGuiSshTests(unittest.TestCase):
    """SSH simulator tests drive the protocol through activated dataset snapshots.

    Simulated data only ever comes from an activated dataset; there is no
    legacy config.json fallback anymore.
    """

    USERNAME = "admin"
    PASSWORD = "admin123"

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.datasets = Path(self.tempdir.name) / "datasets"
        simulator_gui.set_data_dir(self.tempdir.name)
        self.client = simulator_gui.app.test_client()
        self.client.post("/api/dataset-directory/switch", json={"path": str(self.datasets)})

    def tearDown(self):
        simulator_gui.stop_event.set()
        time.sleep(1.2)
        simulator_gui.reset_runtime_state()
        simulator_gui.set_data_dir(str(ROOT))
        self.tempdir.cleanup()

    def create_dataset(self, dataset_id, commands):
        response = self.client.post("/api/datasets", json={
            "id": dataset_id, "name": dataset_id,
            "commands": commands, "rest_routes": []})
        self.assertEqual(201, response.status_code, response.get_json())
        return response.get_json()

    def activate(self, dataset_id, execution_id):
        response = self.client.post("/api/runtime/activate-dataset", json={
            "dataset_id": dataset_id, "execution_id": execution_id})
        self.assertEqual(200, response.status_code, response.get_json())

    def exec_command(self, port, username, password, command):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                "127.0.0.1",
                port=port,
                username=username,
                password=password,
                look_for_keys=False,
                allow_agent=False,
                timeout=10,
            )
            _stdin, stdout, stderr = client.exec_command(command, timeout=10)
            return (
                stdout.read().decode("utf-8", errors="replace"),
                stderr.read().decode("utf-8", errors="replace"),
            )
        finally:
            client.close()

    def test_exec_command_over_ssh_returns_configured_output(self):
        port = free_port()
        command = {"name": "show system general", "description": "查询系统信息",
                   "output": "System Name: OceanStor_24A.Storage\nHealth Status: Normal"}
        dataset = self.create_dataset("ssh-demo", [command])
        self.activate("ssh-demo", "run-1")
        simulator_gui.stop_event.clear()
        threading.Thread(
            target=simulator_gui.run_server,
            args=("127.0.0.1", port, self.USERNAME, self.PASSWORD,
                  list(dataset["commands"])),
            daemon=True,
        ).start()
        time.sleep(1.0)

        stdout, stderr = self.exec_command(
            port, self.USERNAME, self.PASSWORD, "show system general")

        self.assertEqual("", stderr)
        self.assertIn("System Name: OceanStor_24A.Storage", stdout)

    def test_running_server_serves_immutable_activated_snapshot(self):
        port = free_port()
        old_output = "old output " + uuid.uuid4().hex
        new_output = "new output " + uuid.uuid4().hex
        dataset = self.create_dataset("ssh-snap", [
            {"name": "show status", "description": "", "output": old_output}])
        self.activate("ssh-snap", "run-snap")
        simulator_gui.stop_event.clear()
        threading.Thread(
            target=simulator_gui.run_server,
            args=("127.0.0.1", port, self.USERNAME, self.PASSWORD,
                  list(dataset["commands"])),
            daemon=True,
        ).start()
        time.sleep(1.0)

        dataset["commands"][0]["output"] = new_output
        updated = self.client.put("/api/datasets/ssh-snap", json=dataset)
        self.assertEqual(200, updated.status_code, updated.get_json())

        stdout, stderr = self.exec_command(port, self.USERNAME, self.PASSWORD, "show status")
        self.assertEqual("", stderr)
        self.assertIn(old_output, stdout)
        self.assertNotIn(new_output, stdout)

    def test_stop_then_start_waits_for_restart_and_uses_reactivated_data(self):
        port = free_port()
        old_output = "old restart output " + uuid.uuid4().hex
        new_output = "new restart output " + uuid.uuid4().hex
        self.create_dataset("ssh-restart", [
            {"name": "show version", "description": "", "output": old_output}])
        self.activate("ssh-restart", "run-a")

        start = self.client.post("/api/server/start", json={"port": port})
        self.assertEqual(200, start.status_code, start.get_json())
        time.sleep(1.0)

        stdout, stderr = self.exec_command(port, self.USERNAME, self.PASSWORD, "show version")
        self.assertEqual("", stderr)
        self.assertIn(old_output, stdout)

        released = self.client.post("/api/runtime/release", json={"execution_id": "run-a"})
        self.assertEqual(200, released.status_code, released.get_json())
        dataset = self.client.get("/api/datasets/ssh-restart").get_json()
        dataset["commands"][0]["output"] = new_output
        updated = self.client.put("/api/datasets/ssh-restart", json=dataset)
        self.assertEqual(200, updated.status_code, updated.get_json())
        self.activate("ssh-restart", "run-b")

        self.client.post("/api/server/stop")
        start = self.client.post("/api/server/start", json={"port": port})
        self.assertEqual(200, start.status_code, start.get_json())
        time.sleep(1.0)

        stdout, stderr = self.exec_command(port, self.USERNAME, self.PASSWORD, "show version")
        self.assertEqual("", stderr)
        self.assertIn(new_output, stdout)
        self.assertNotIn(old_output, stdout)

        logs = []
        while True:
            try:
                logs.append(simulator_gui.log_queue.get_nowait())
            except Exception:
                break
        self.assertFalse(
            any("Cannot bind port" in log for log in logs),
            "\n".join(logs),
        )

    def test_start_api_saves_bind_address_and_passes_it_to_server(self):
        port = free_port()
        captured_args = []

        def fake_run_server(*args):
            captured_args.append(args)

        from smartkit_simulator.application import application
        old_runner = application.ssh_runner
        try:
            application.ssh_runner = fake_run_server
            simulator_gui.save_app_settings({
                "ssh_server": {"username": "settings-user",
                               "password": "settings-pass"},
            })

            response = simulator_gui.app.test_client().post(
                "/api/server/start",
                json={
                    "bind_address": "0.0.0.0",
                    "port": port,
                },
            )
            time.sleep(0.2)

            saved_settings = simulator_gui.load_app_settings()
            self.assertEqual(200, response.status_code)
            self.assertEqual("0.0.0.0", saved_settings["ssh_server"]["bind_address"])
            self.assertEqual(port, saved_settings["ssh_server"]["port"])
            self.assertEqual("settings-user", saved_settings["ssh_server"]["username"])
            self.assertEqual("settings-pass", saved_settings["ssh_server"]["password"])
            self.assertTrue(captured_args)
            self.assertEqual("0.0.0.0", captured_args[0][0])
            self.assertEqual(port, captured_args[0][1])
            self.assertEqual("settings-user", captured_args[0][2])
            self.assertEqual("settings-pass", captured_args[0][3])
        finally:
            application.ssh_runner = old_runner

    def test_command_output_uses_crlf_line_endings_for_terminal_alignment(self):
        output = "first\nsecond\r\nthird"

        self.assertEqual(
            "first\r\nsecond\r\nthird\r\n",
            simulator_gui.format_command_output(output),
        )

    def test_resource_path_uses_project_directory(self):
        self.assertEqual(
            str(ROOT / "workbench.html"),
            simulator_gui.resource_path("workbench.html"),
        )

    def test_gui_workbench_exists_for_development_startup(self):
        self.assertTrue((ROOT / "workbench.html").exists())


if __name__ == "__main__":
    unittest.main()
