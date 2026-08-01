# SmartKit Simulator Electron 重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 SmartKit Storage Simulator 从「Python 脚本 + 浏览器」重构为「Electron 便携版 exe」，双击即用，关窗即退出。

**Architecture:** Electron 主进程作为外壳，spawn PyInstaller 打包的自包含 Python 后端（Flask + Paramiko）；后端 `--headless` 模式绑定随机端口并打印 `SMARTKIT_READY_PORT=<port>` 信号；Electron 解析信号后用 BrowserWindow 加载 `http://127.0.0.1:<port>`；关窗时 `taskkill /T /F` 杀后端进程树。前端 `index.html` 与 SSH 逻辑（Paramiko）零改动。

**Tech Stack:** Electron 31 + electron-builder（portable target）、Python 3.12+ / Flask 3+ / Paramiko 5+（现有）、PyInstaller 6.21（venv 已装）。

**Spec:** `docs/superpowers/specs/2026-08-01-electron-refactor-design.md`

## Global Constraints

- Windows-only 打包（`electron-builder --win portable`），目标机为 Windows
- 目标机**已装 Python** 但很可能没有 flask/paramiko → 后端必须 PyInstaller 自包含
- 交付物为**免安装便携版 exe**（electron-builder portable 单文件）
- **关窗即退出**：关闭窗口 → kill 后端进程树 → app.quit()；无托盘、无自动重启
- `index.html` **不允许改动**；`server.py`（CLI 旧版）不动
- 安全基线：`contextIsolation: true`、`nodeIntegration: false`、`sandbox: true`
- 数据目录：portable 模式 = `PORTABLE_EXECUTABLE_DIR`（配置随 exe 走）；打包非 portable = `app.getPath("userData")`；dev 模式 = 项目根目录
- 现有测试 `tests/test_simulator_gui.py`、`tests/test_index_html.js` 必须保持通过
- 后端兼容参数：`--headless`、`--data-dir`；不带参数时行为与现状完全一致（浏览器 + 5800-5899 扫描）
- README 不得包含 `start.bat`、`stop.bat`、`package_portable.ps1`、`便携发布包`（test_portability 断言）

---

### Task 1: 后端 headless 模式（simulator_gui.py + tests/test_headless.py）

**Files:**
- Modify: `simulator_gui.py`（约 30 行改动：导入、DATA_DIR、resource_path、argparse、headless 启动分支）
- Create: `tests/test_headless.py`
- Test: `tests/test_simulator_gui.py`（保持通过）

**Interfaces:**
- Produces:
  - `simulator_gui.parse_args(argv=None) -> argparse.Namespace`（字段：`headless: bool`、`data_dir: str|None`）
  - `simulator_gui.set_data_dir(path: str) -> None`（更新全局 `DATA_DIR`/`CONFIG_PATH`/`HOST_KEY_PATH`，并 `os.makedirs`）
  - `simulator_gui.run_headless() -> None`（绑定 `127.0.0.1:0`，打印 `SMARTKIT_READY_PORT=<port>`，`serve_forever()`）
  - headless 模式 stdout 契约：单行 `SMARTKIT_READY_PORT=<port>`（Electron main.js 依赖此格式）

- [ ] **Step 1: 写失败测试 `tests/test_headless.py`**

```python
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

    def test_plain_mode_does_not_use_headless_port_signal(self):
        # 不带 --headless 时不得打印 SMARTKIT_READY_PORT（保持原 CLI 行为）
        proc, lines = self._spawn()
        try:
            # 原模式仍会做 5800-5899 扫描并打印 "GUI running at ..."
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_headless -v`
Expected: FAIL（`simulator_gui.py` 尚无 `--headless` 参数，argparse 报错 / 无就绪信号）

- [ ] **Step 3: 修改 `simulator_gui.py`**

顶部导入区（第 4 行）追加 `sys`：

```python
import json, os, queue, socket, sys, threading, time, datetime, random, string, webbrowser
```

`resource_path`（第 11-12 行）改为 PyInstaller 兼容：

```python
def resource_path(relative_path):
    base = getattr(sys, "_MEIPASS", BASE_DIR)
    return os.path.join(base, relative_path)
```

`writable_path` 与 DATA_DIR（第 14-18 行区域）：

```python
DATA_DIR = BASE_DIR

def writable_path(relative_path):
    return os.path.join(DATA_DIR, relative_path)

def set_data_dir(path):
    global DATA_DIR, CONFIG_PATH, HOST_KEY_PATH
    DATA_DIR = os.path.abspath(path)
    os.makedirs(DATA_DIR, exist_ok=True)
    CONFIG_PATH = writable_path("config.json")
    HOST_KEY_PATH = os.path.join(DATA_DIR, "host_key")

CONFIG_PATH = writable_path("config.json")
HOST_KEY_PATH = os.path.join(DATA_DIR, "host_key")
```

`__main__` 块（第 271-285 行）整体替换：

```python
def parse_args(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="SmartKit Storage Simulator")
    parser.add_argument("--headless", action="store_true",
                        help="Run without browser; print SMARTKIT_READY_PORT=<port>")
    parser.add_argument("--data-dir", default=None,
                        help="Directory for config.json and host_key")
    return parser.parse_args(argv)

def run_headless():
    from werkzeug.serving import make_server
    server = make_server("127.0.0.1", 0, app, threaded=True)
    print(f"SMARTKIT_READY_PORT={server.server_port}", flush=True)
    server.serve_forever()

if __name__ == "__main__":
    args = parse_args()
    if args.data_dir:
        set_data_dir(args.data_dir)
    if args.headless:
        run_headless()
    else:
        port = 5800
        for p in range(5800, 5900):
            try:
                s = socket.socket()
                s.bind(("127.0.0.1", p))
                s.close()
                port = p
                break
            except OSError:
                continue
        url = f"http://127.0.0.1:{port}"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        print(f"GUI running at {url}")
        app.run(host="127.0.0.1", port=port, debug=False)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_headless tests.test_simulator_gui -v`
Expected: 全部 PASS（headless 新测试 3 个 + 原 SSH 回归测试）

- [ ] **Step 5: 提交**

```bash
git add simulator_gui.py tests/test_headless.py
git commit -m "feat: 后端支持 --headless/--data-dir 模式，供 Electron 外壳调用"
```

---

### Task 2: Electron 外壳（electron/package.json + electron/main.js + .gitignore）

**Files:**
- Create: `electron/package.json`
- Create: `electron/main.js`
- Modify: `.gitignore`（追加 `node_modules/`）
- Test: 语法检查 `node --check` + 手动 `npm start` 冒烟

**Interfaces:**
- Consumes: Task 1 的 headless stdout 契约 `SMARTKIT_READY_PORT=<port>`
- Produces:
  - `electron/package.json` scripts: `start`（electron .）、`dist`（electron-builder --win portable）
  - `electron/main.js` 行为：spawn 后端 → 解析端口 → BrowserWindow(1280×800) → 关窗杀进程树

- [ ] **Step 1: 创建 `electron/package.json`**

```json
{
  "name": "smartkit-simulator",
  "version": "1.0.0",
  "description": "SmartKit Storage Simulator - SSH storage device simulator",
  "main": "main.js",
  "author": "SmartKit",
  "license": "UNLICENSED",
  "private": true,
  "scripts": {
    "start": "electron .",
    "dist": "electron-builder --win portable"
  },
  "devDependencies": {
    "electron": "^31.0.0",
    "electron-builder": "^24.13.3"
  },
  "build": {
    "appId": "com.smartkit.simulator",
    "productName": "SmartKit Simulator",
    "files": ["main.js", "package.json"],
    "extraResources": [
      {
        "from": "../dist/backend/simulator_gui.exe",
        "to": "backend/simulator_gui.exe"
      }
    ],
    "win": {
      "target": ["portable"]
    },
    "portable": {
      "artifactName": "SmartKit-Simulator-${version}.exe"
    }
  }
}
```

- [ ] **Step 2: 创建 `electron/main.js`**

```javascript
const { app, BrowserWindow, dialog } = require("electron");
const { spawn, execFileSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const readline = require("readline");

const READY_TIMEOUT_MS = 30000;

let backendProcess = null;
let mainWindow = null;
let readyPort = null;

function projectRoot() {
  return path.resolve(__dirname, "..");
}

function resolveBackendCommand() {
  const root = projectRoot();
  if (app.isPackaged) {
    return {
      command: path.join(process.resourcesPath, "backend", "simulator_gui.exe"),
      args: [],
    };
  }
  const venvPython = path.join(root, ".venv", "Scripts", "python.exe");
  const python = fs.existsSync(venvPython) ? venvPython : "python";
  return { command: python, args: [path.join(root, "simulator_gui.py")] };
}

function resolveDataDir() {
  if (process.env.PORTABLE_EXECUTABLE_DIR) {
    return process.env.PORTABLE_EXECUTABLE_DIR;
  }
  if (app.isPackaged) {
    return app.getPath("userData");
  }
  return projectRoot();
}

function killBackendTree() {
  if (!backendProcess || !backendProcess.pid) return;
  try {
    execFileSync("taskkill", ["/pid", String(backendProcess.pid), "/T", "/F"], {
      stdio: "ignore",
    });
  } catch (_) {
    try { backendProcess.kill(); } catch (_) {}
  }
  backendProcess = null;
}

function showFatal(message) {
  dialog.showErrorBox("SmartKit Simulator", message);
  app.exit(1);
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const { command, args } = resolveBackendCommand();
    const fullArgs = [...args, "--headless", "--data-dir", resolveDataDir()];
    backendProcess = spawn(command, fullArgs, {
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stderr = "";
    backendProcess.stderr.on("data", (d) => { stderr += d.toString(); });
    backendProcess.on("error", (err) => {
      reject(new Error(`Failed to start backend: ${err.message}\n${stderr}`));
    });
    const timer = setTimeout(() => {
      reject(new Error(`Backend startup timed out after ${READY_TIMEOUT_MS / 1000}s\n${stderr}`));
    }, READY_TIMEOUT_MS);
    const rl = readline.createInterface({ input: backendProcess.stdout });
    rl.on("line", (line) => {
      const m = line.match(/^SMARTKIT_READY_PORT=(\d+)$/);
      if (m) {
        clearTimeout(timer);
        rl.close();
        resolve(parseInt(m[1], 10));
      }
    });
  });
}

app.whenReady().then(async () => {
  try {
    readyPort = await startBackend();
  } catch (err) {
    showFatal(err.message);
    return;
  }
  backendProcess.on("exit", (code) => {
    showFatal(`Backend exited unexpectedly (code ${code}).`);
  });
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.loadURL(`http://127.0.0.1:${readyPort}`);
});

app.on("window-all-closed", () => {
  killBackendTree();
  app.quit();
});

app.on("will-quit", killBackendTree);
```

- [ ] **Step 3: 更新 `.gitignore`**

追加一行：

```
node_modules/
```

- [ ] **Step 4: 语法检查 + 安装依赖 + 开发冒烟**

```bash
node --check electron/main.js
cd electron && npm install
```

Expected: `node --check` 无输出（成功）；`npm install` 完成（Electron 二进制约 100MB，需要网络）。

开发冒烟（手动）：在项目根目录执行 `cd electron; npm start`，预期：Electron 窗口出现、加载 Flask GUI、无黑窗、无控制台残留。手动关闭窗口后确认任务管理器无 `python.exe` 残留（此步由执行者确认）。

- [ ] **Step 5: 提交**

```bash
git add .gitignore electron/package.json electron/main.js
git commit -m "feat: 新增 Electron 外壳（spawn 后端、关窗即退出、便携版构建配置）"
```

---

### Task 3: README 更新 + test_portability.py 适配

**Files:**
- Modify: `README.md`
- Modify: `tests/test_portability.py`
- Test: `python -m unittest tests.test_portability` + 全量回归

**Interfaces:**
- Consumes: Task 1（headless 参数）、Task 2（electron 目录结构）
- Produces: README 文档化 dev 模式与打包流程；portability 测试断言与新结构一致

**背景**：现有 `test_portability.py::test_readme_documents_development_startup_only` 断言 README **不含** "PyInstaller"/"build_exe.ps1"。本次重构引入 PyInstaller 打包，该断言必须改为允许并更新为正向断言。

- [ ] **Step 1: 修改 `README.md`**

- 在「功能概览」后追加一节：

```markdown
## Electron 桌面版（推荐）

双击 `SmartKit-Simulator-1.0.0.exe` 即可打开桌面界面，无需浏览器、无需手动启动 Python 脚本。
关闭窗口即退出，SSH 服务随之停止。

- 桌面版由 Electron 外壳 + 内嵌后端组成，后端自动在随机空闲端口启动。
- 配置（`config.json`、`host_key`）保存在 exe 同级目录，随 exe 拷贝移动。
```

- 「启动 GUI」一节改为并列两种方式：

```markdown
## 启动 GUI

方式一（桌面版，推荐）：运行打包好的 `SmartKit-Simulator-1.0.0.exe`。

方式二（浏览器版，开发用）：使用启动脚本 `.\start_gui.ps1`，启动后访问
`http://127.0.0.1:5800`（被占用时自动尝试 5801-5899）。
```

- 追加「打包」一节：

```markdown
## 打包为桌面 exe

```powershell
.\build.ps1
```

依次执行 PyInstaller（后端 → `dist\backend\simulator_gui.exe`）和 electron-builder
（前端外壳 → `electron\dist\SmartKit-Simulator-1.0.0.exe`）。

## 开发 Electron 外壳

```powershell
cd electron
npm install
npm start          # 自动用 .venv 的 python 启动后端（--headless --data-dir 项目根目录）
```
```

- 更新「项目结构」代码块，追加：

```text
  electron/
    package.json        Electron 外壳依赖与构建配置
    main.js             Electron 主进程（spawn 后端、关窗即退出）
  build.ps1             一键打包脚本（PyInstaller + electron-builder）
  requirements-build.txt  打包构建依赖（PyInstaller）
```

- 「依赖」一节追加：`PyInstaller`（仅打包时需要，见 `requirements-build.txt`）

- 注意：README 全文不得出现 `start.bat`、`stop.bat`、`package_portable.ps1`、`便携发布包`

- [ ] **Step 2: 修改 `tests/test_portability.py`**

- `test_readme_documents_development_startup_only` 替换为：

```python
    def test_readme_documents_development_and_desktop_build(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("python -m venv .venv", readme)
        self.assertIn(".\\start_gui.ps1", readme)
        self.assertIn("SmartKit-Simulator-1.0.0.exe", readme)
        self.assertIn("build.ps1", readme)
        self.assertIn("electron-builder", readme)
        self.assertNotIn("start.bat", readme)
        self.assertNotIn("stop.bat", readme)
        self.assertNotIn("package_portable.ps1", readme)
        self.assertNotIn("便携发布包", readme)
```

- `test_scripts_and_docs_do_not_reference_codex_runtime_paths` 的 files 列表追加两个新文件：

```python
        files = [
            ROOT / "README.md",
            ROOT / "run.ps1",
            ROOT / "start_gui.ps1",
            ROOT / "build.ps1",
            ROOT / "electron" / "main.js",
        ]
```

- 新增测试（放在类末尾）：

```python
    def test_electron_shell_files_exist(self):
        self.assertTrue((ROOT / "electron" / "package.json").exists())
        self.assertTrue((ROOT / "electron" / "main.js").exists())

    def test_build_script_exists_and_is_powershell(self):
        script = (ROOT / "build.ps1").read_text(encoding="utf-8")
        self.assertIn("PyInstaller", script)
        self.assertIn("electron-builder", script)
```

- [ ] **Step 3: 运行测试确认通过**

Run: `python -m unittest tests.test_portability -v`
Expected: PASS（注意 Task 4 才会创建 `build.ps1` —— 若先执行本任务，`test_build_script_exists_and_is_powershell` 会失败，因此本任务与 Task 4 必须同批执行，或先建 `build.ps1` 空壳。**推荐顺序：先执行 Task 4 Step 1 创建 `build.ps1`，再回来跑本任务测试**。）

- [ ] **Step 4: 提交**

```bash
git add README.md tests/test_portability.py
git commit -m "docs: 更新 README 支持 Electron 桌面版与打包说明，适配可移植性测试"
```

---

### Task 4: 打包脚本（build.ps1 + requirements-build.txt）

**Files:**
- Create: `build.ps1`
- Create: `requirements-build.txt`
- Test: 执行打包 + 产物验证

**Interfaces:**
- Consumes: Task 1（headless 后端）、Task 2（electron 目录与构建配置）
- Produces: `dist/backend/simulator_gui.exe`（PyInstaller）、`electron/dist/SmartKit-Simulator-1.0.0.exe`（最终交付物）

- [ ] **Step 1: 创建 `build.ps1`**

```powershell
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# 1) PyInstaller 打后端
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Missing .venv. Run: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt -r requirements-build.txt" }
& $py -m PyInstaller --onefile --name simulator_gui `
    --add-data "index.html;." `
    --add-data "config.json;." `
    --distpath (Join-Path $root "dist\backend") `
    --workpath (Join-Path $root "build\pyinstaller") `
    --specpath (Join-Path $root "build\pyinstaller") `
    (Join-Path $root "simulator_gui.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# 2) electron-builder 打便携版
Push-Location (Join-Path $root "electron")
if (-not (Test-Path "node_modules")) { npm install }
npm run dist
if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }
Pop-Location

Write-Host ""
Write-Host "Done. Deliverable:"
Write-Host "  $root\electron\dist\SmartKit-Simulator-1.0.0.exe"
```

- [ ] **Step 2: 创建 `requirements-build.txt`**

```
pyinstaller>=6.0
```

- [ ] **Step 3: 执行打包并验证产物**

```powershell
.\build.ps1
Test-Path dist\backend\simulator_gui.exe
Test-Path electron\dist\SmartKit-Simulator-1.0.0.exe
```

Expected: 两个 `Test-Path` 均为 True。

额外验证后端 exe 的 headless 契约（后端自包含，不依赖 venv）：

```powershell
$tmp = "$env:TEMP\smartkit-exe-test"; New-Item -ItemType Directory -Force $tmp | Out-Null
$p = Start-Process -FilePath "dist\backend\simulator_gui.exe" -ArgumentList "--headless","--data-dir",$tmp -PassThru -RedirectStandardOutput "$env:TEMP\sk-out.txt" -RedirectStandardError "$env:TEMP\sk-err.txt"
Start-Sleep -Seconds 6
Get-Content "$env:TEMP\sk-out.txt"   # 期望包含 SMARTKIT_READY_PORT=<port>
Get-Content "$env:TEMP\sk-err.txt"   # 期望为空或仅警告
Stop-Process -Id $p.Id -Force
```

- [ ] **Step 4: 运行全量测试**

Run: `python -m unittest tests.test_simulator_gui tests.test_headless tests.test_portability -v` 且 `node tests/test_index_html.js`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add build.ps1 requirements-build.txt
git commit -m "build: 新增一键打包脚本（PyInstaller 后端 + electron-builder 便携版）"
```

---

### Task 5: 最终验证（手动冒烟清单）

**Files:** 无代码改动；仅交付验证。

- [ ] **Step 1: 运行全量自动化测试**

```powershell
python -m py_compile simulator_gui.py tests/test_simulator_gui.py tests/test_headless.py tests/test_portability.py
python -m unittest tests.test_simulator_gui tests.test_headless tests.test_portability -v
node tests/test_index_html.js
```

Expected: 全部通过。

- [ ] **Step 2: 双击最终 exe 冒烟（人工执行）**

1. 双击 `electron\dist\SmartKit-Simulator-1.0.0.exe`
2. 窗口出现，加载 SSH 模拟器界面，无黑窗/控制台
3. 点击 **Start Server** → 状态变 Running
4. PowerShell 中执行 `ssh admin@127.0.0.1 -p 2222 show system general` → 输出 System General Information
5. 修改一条命令输出 → Save Command → 重启 SSH 服务 → 新输出生效
6. 关闭窗口 → 任务管理器确认无 `simulator_gui.exe` / `python.exe` 残留
7. 将 exe 拷贝到另一目录运行 → 配置（config.json）跟随 exe

- [ ] **Step 3: 收尾提交（若 README/测试有补充修正）**

```bash
git status
git add -A
git commit -m "chore: 重构收尾修正"
```

（若 Task 3 的 `build.ps1` 断言已在 Task 4 前就绪，本步可跳过。）

---

## Self-Review 记录

**1. Spec coverage 核对：**
- ✅ headless 模式 + data-dir（Task 1，对应 spec §3）
- ✅ Electron 主进程生命周期/错误处理/安全基线（Task 2，对应 spec §4）
- ✅ 两级打包 + build.ps1（Task 4，对应 spec §5）
- ✅ 目录结构（Task 2/4，对应 spec §6）
- ✅ 测试策略：新增 test_headless、更新 test_portability、保留原测试（Task 1/3，对应 spec §7）
- ✅ 验证清单（Task 5，对应 spec §8）
- ✅ Out of scope 全部遵守（index.html/server.py/托盘/自动更新不涉及）

**2. Placeholder 扫描：** 无 TBD/TODO；所有步骤含具体代码或命令。

**3. 类型/命名一致性：**
- stdout 契约 `SMARTKIT_READY_PORT=<port>` 在 Task 1 测试、Task 1 实现、Task 2 main.js 三处一致
- `--headless` / `--data-dir` 参数名在 Python argparse、PowerShell Start-Process、main.js spawn 三处一致
- 产物路径：`dist/backend/simulator_gui.exe`、`electron/dist/SmartKit-Simulator-1.0.0.exe` 在 build.ps1、electron package.json extraResources、README 三处一致
- `PORTABLE_EXECUTABLE_DIR` 回退链与 spec §4.1.1 一致

**4. 依赖顺序风险：** Task 3 的 `test_build_script_exists_and_is_powershell` 依赖 Task 4 创建的 `build.ps1` —— 已在 Task 3 Step 3 中明确标注执行顺序要求。
