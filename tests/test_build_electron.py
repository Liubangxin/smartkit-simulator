import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "build_tools" / "SevenZipWrapper.ps1"


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


class SevenZipWrapperTests(unittest.TestCase):
    def test_restore_retries_while_wrapper_is_temporarily_locked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            electron_dir = Path(temp_dir) / "electron"
            seven_zip_dir = electron_dir / "node_modules" / "7zip-bin" / "win" / "x64"
            seven_zip_dir.mkdir(parents=True)
            wrapper = seven_zip_dir / "7za.exe"
            original = seven_zip_dir / "7za_orig.exe"
            marker = Path(temp_dir) / "locked"
            wrapper.write_text("wrapper", encoding="utf-8")
            original.write_text("original", encoding="utf-8")

            holder_script = (
                f"$stream = [System.IO.File]::Open({ps_quote(wrapper)}, 'Open', "
                "'ReadWrite', 'None'); "
                f"[System.IO.File]::WriteAllText({ps_quote(marker)}, 'locked'); "
                "Start-Sleep -Milliseconds 750; $stream.Dispose()"
            )
            holder = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", holder_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(marker.exists(), "lock holder did not start")

                restore_script = (
                    f". {ps_quote(HELPER)}; "
                    f"Restore-7zaOriginal -ElectronDir {ps_quote(electron_dir)}"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", restore_script],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            finally:
                holder.communicate(timeout=5)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("original", wrapper.read_text(encoding="utf-8"))
            self.assertFalse(original.exists())


if __name__ == "__main__":
    unittest.main()
