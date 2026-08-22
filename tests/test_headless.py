import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


class HeadlessModeTests(unittest.TestCase):
    def _spawn(self, *extra_args):
        proc = subprocess.Popen(
            [PYTHON, str(ROOT / "simulator_gui.py"), *extra_args],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        lines = queue.Queue()

        def reader():
            for line in proc.stdout:
                lines.put(line.rstrip("\n"))

        threading.Thread(target=reader, daemon=True).start()
        return proc, lines

    def _wait_ready(self, proc, lines, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = lines.get(timeout=0.5)
            except queue.Empty:
                if proc.poll() is not None:
                    stderr = proc.stderr.read()
                    self.fail(f"backend exited early, stderr:\n{stderr}")
                continue
            m = re.match(r"^SMARTKIT_READY_PORT=(\d+)$", line)
            if m:
                return int(m.group(1))
        proc.terminate()
        self.fail("SMARTKIT_READY_PORT signal not received within timeout")

    def test_headless_prints_ready_port_and_serves_api(self):
        proc, lines = self._spawn("--headless")
        try:
            port = self._wait_ready(proc, lines)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/config", timeout=5) as r:
                data = json.load(r)
            self.assertIn("commands", data)
            self.assertIn("server", data)
        finally:
            proc.terminate()
            proc.wait(timeout=10)

    def test_headless_writes_config_to_data_dir(self):
        with tempfile.TemporaryDirectory() as d:
            proc, lines = self._spawn("--headless", "--data-dir", d)
            try:
                port = self._wait_ready(proc, lines)
                payload = {
                    "server": {"bind_address": "127.0.0.1", "port": 2222,
                               "username": "admin", "password": "admin123"},
                    "commands": [{"name": "test cmd", "description": "d", "output": "o"}],
                }
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/config",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    self.assertEqual(200, r.status)
                config_path = Path(d) / "config.json"
                self.assertTrue(config_path.exists(), "config.json must be written to --data-dir")
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual("test cmd", saved["commands"][0]["name"])
            finally:
                proc.terminate()
                proc.wait(timeout=10)

    def test_headless_uses_requested_management_port(self):
        probe = __import__("socket").socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        proc, lines = self._spawn("--headless", "--management-port", str(port))
        try:
            ready_port = self._wait_ready(proc, lines)
            self.assertEqual(port, ready_port)
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/runtime/health", timeout=5
            ) as response:
                self.assertEqual("ready", json.load(response)["status"])
        finally:
            proc.terminate()
            proc.wait(timeout=10)

    def test_plain_mode_does_not_use_headless_port_signal(self):
        # Without --headless, must NOT print SMARTKIT_READY_PORT (preserve original CLI behavior)
        proc, lines = self._spawn()
        try:
            # Plain mode still does the 35800-35899 scan and prints "GUI running at ..."
            deadline = time.time() + 30
            saw_gui = False
            while time.time() < deadline:
                try:
                    line = lines.get(timeout=0.5)
                except queue.Empty:
                    if proc.poll() is not None:
                        break
                    continue
                if "GUI running at" in line:
                    saw_gui = True
                    break
                self.assertNotRegex(line, r"^SMARTKIT_READY_PORT=")
            self.assertTrue(saw_gui, "plain mode should print 'GUI running at'")
        finally:
            proc.terminate()
            proc.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
