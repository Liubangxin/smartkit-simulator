from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PortabilityTests(unittest.TestCase):
    def test_scripts_and_docs_do_not_reference_codex_runtime_paths(self):
        files = [
            ROOT / "README.md",
            ROOT / "run.ps1",
            ROOT / "start_gui.ps1",
        ]

        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("codex-runtimes", text)
            self.assertNotIn(".cache\\codex", text)
            self.assertNotIn("wangxinxin", text)

    def test_powershell_scripts_do_not_call_indexed_python_command(self):
        files = [
            ROOT / "run.ps1",
            ROOT / "start_gui.ps1",
        ]

        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("& $python[0]", text)
            self.assertIn("$pythonCommand = $python[0]", text)

    def test_gui_start_script_prefers_project_virtual_environment(self):
        script = (ROOT / "start_gui.ps1").read_text(encoding="utf-8")

        self.assertIn(".venv\\Scripts\\python.exe", script)
        self.assertIn("Test-Path $venvPython", script)

    def test_portable_package_entrypoint_was_removed(self):
        self.assertFalse((ROOT / "package_portable.ps1").exists())

    def test_readme_documents_development_and_electron_build(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("python -m venv .venv", readme)
        self.assertIn(".\\start_gui.ps1", readme)
        self.assertNotIn("便携发布包", readme)
        self.assertNotIn("start.bat", readme)
        self.assertNotIn("stop.bat", readme)
        self.assertNotIn("package_portable.ps1", readme)
        self.assertIn("build_electron.ps1 -Clean", readme)
        self.assertIn("electron/dist/SmartKit-Simulator-1.0.0.exe", readme)
        self.assertIn("PyInstaller", readme)
        self.assertNotIn("build_exe.ps1", readme)
        self.assertIn("--automation", readme)
        self.assertIn("--management-port 5800", readme)

    def test_electron_entrypoint_supports_automation_launch_contract(self):
        source = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
        self.assertIn('process.argv.includes("--automation")', source)
        self.assertIn('commandLineValue("--management-port")', source)
        self.assertIn('commandLineValue("--data-dir")', source)
        self.assertIn('commandLineValue("--attach-management-url")', source)
        self.assertIn('fullArgs.push("--management-port", String(managementPort))', source)

    def test_electron_window_is_visible_while_management_page_loads(self):
        source = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")

        self.assertIn("show: true", source)
        self.assertNotIn('mainWindow.once("ready-to-show"', source)
        self.assertIn("screen.getPrimaryDisplay().workArea", source)
        self.assertIn("mainWindow.setBounds", source)
        self.assertIn("mainWindow.show()", source)
        self.assertIn("mainWindow.focus()", source)


if __name__ == "__main__":
    unittest.main()
