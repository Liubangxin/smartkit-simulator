import socket
import sys
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
    def tearDown(self):
        simulator_gui.stop_event.set()
        time.sleep(1.2)

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
        config = simulator_gui.load_config()
        port = free_port()
        simulator_gui.stop_event.clear()
        threading.Thread(
            target=simulator_gui.run_server,
            args=(
                "127.0.0.1",
                port,
                config["server"]["username"],
                config["server"]["password"],
                list(config["commands"]),
            ),
            daemon=True,
        ).start()
        time.sleep(1.0)

        stdout, stderr = self.exec_command(
            port,
            config["server"]["username"],
            config["server"]["password"],
            "show system general",
        )

        self.assertEqual("", stderr)
        self.assertIn("System General Information", stdout)

    def test_running_server_uses_saved_command_output_changes(self):
        original_config = simulator_gui.load_config()
        port = free_port()
        command_name = "show system general"
        old_output = "old output " + uuid.uuid4().hex
        new_output = "new output " + uuid.uuid4().hex
        test_config = {
            "server": {
                "port": port,
                "username": original_config["server"]["username"],
                "password": original_config["server"]["password"],
            },
            "commands": [
                {
                    "name": command_name,
                    "description": "test command",
                    "output": old_output,
                }
            ],
        }

        try:
            simulator_gui.save_config(test_config)
            simulator_gui.stop_event.clear()
            threading.Thread(
                target=simulator_gui.run_server,
                args=(
                    "127.0.0.1",
                    port,
                    test_config["server"]["username"],
                    test_config["server"]["password"],
                    list(test_config["commands"]),
                ),
                daemon=True,
            ).start()
            time.sleep(1.0)

            saved_config = {
                "server": dict(test_config["server"]),
                "commands": [
                    {
                        "name": command_name,
                        "description": "test command",
                        "output": new_output,
                    }
                ],
            }
            simulator_gui.save_config(saved_config)
            stdout, stderr = self.exec_command(
                port,
                test_config["server"]["username"],
                test_config["server"]["password"],
                command_name,
            )

            self.assertEqual("", stderr)
            self.assertIn(new_output, stdout)
            self.assertNotIn(old_output, stdout)
        finally:
            simulator_gui.save_config(original_config)

    def test_stop_then_start_waits_for_restart_and_uses_saved_output(self):
        original_config = simulator_gui.load_config()
        port = free_port()
        command_name = "show system general"
        old_output = "old restart output " + uuid.uuid4().hex
        new_output = "new restart output " + uuid.uuid4().hex
        username = original_config["server"]["username"]
        password = original_config["server"]["password"]

        try:
            simulator_gui.save_config(
                {
                    "server": {"port": port, "username": username, "password": password},
                    "commands": [
                        {
                            "name": command_name,
                            "description": "test command",
                            "output": old_output,
                        }
                    ],
                }
            )
            client = simulator_gui.app.test_client()
            client.post(
                "/api/server/start",
                json={"port": port, "username": username, "password": password},
            )
            time.sleep(1.0)

            simulator_gui.save_config(
                {
                    "server": {"port": port, "username": username, "password": password},
                    "commands": [
                        {
                            "name": command_name,
                            "description": "test command",
                            "output": new_output,
                        }
                    ],
                }
            )
            client.post("/api/server/stop")
            start_response = client.post(
                "/api/server/start",
                json={"port": port, "username": username, "password": password},
            )
            time.sleep(1.0)

            stdout, stderr = self.exec_command(port, username, password, command_name)

            self.assertEqual(200, start_response.status_code)
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
        finally:
            simulator_gui.save_config(original_config)

    def test_start_api_saves_bind_address_and_passes_it_to_server(self):
        original_config = simulator_gui.load_config()
        port = free_port()
        captured_args = []

        def fake_run_server(*args):
            captured_args.append(args)

        old_run_server = simulator_gui.run_server
        try:
            simulator_gui.run_server = fake_run_server
            simulator_gui.save_config(
                {
                    "server": {
                        "port": 2222,
                        "username": "admin",
                        "password": "admin123",
                    },
                    "commands": [],
                }
            )

            response = simulator_gui.app.test_client().post(
                "/api/server/start",
                json={
                    "bind_address": "0.0.0.0",
                    "port": port,
                    "username": "admin",
                    "password": "admin123",
                },
            )
            time.sleep(0.2)

            saved_config = simulator_gui.load_config()
            self.assertEqual(200, response.status_code)
            self.assertEqual("0.0.0.0", saved_config["server"]["bind_address"])
            self.assertTrue(captured_args)
            self.assertEqual("0.0.0.0", captured_args[0][0])
            self.assertEqual(port, captured_args[0][1])
        finally:
            simulator_gui.run_server = old_run_server
            simulator_gui.save_config(original_config)

    def test_command_output_uses_crlf_line_endings_for_terminal_alignment(self):
        output = "first\nsecond\r\nthird"

        self.assertEqual(
            "first\r\nsecond\r\nthird\r\n",
            simulator_gui.format_command_output(output),
        )

    def test_resource_path_uses_project_directory(self):
        self.assertEqual(
            str(ROOT / "index.html"),
            simulator_gui.resource_path("index.html"),
        )

    def test_gui_index_html_exists_for_development_startup(self):
        self.assertTrue((ROOT / "index.html").exists())


if __name__ == "__main__":
    unittest.main()
