# SmartKit Simulator Electron 重构设计文档

日期：2026-08-01
状态：待用户审阅

## 1. 背景与目标

### 现状

SmartKit Storage Simulator 是本地 SSH 存储设备模拟器，当前技术栈：

- **Python 3.12+ / Flask / Paramiko**：`simulator_gui.py` 同时承载 Flask Web GUI（端口 5800-5899）和内嵌 Paramiko SSH 服务（默认 2222）
- **单页前端**：`index.html`，无构建步骤，通过 `fetch("/api/...")` 与后端通信
- **配置**：`config.json`（SSH 服务参数 + 命令列表），`host_key`（SSH 主机密钥，运行时生成）
- **启动方式**：需要安装 Python + pip 依赖，通过 `start_gui.ps1` 启动，浏览器访问 `http://127.0.0.1:5800`

### 用户需求

1. 重构为 **Electron 框架**，在 Windows 上**双击 exe 即可打开使用**
2. 交付形式：**免安装便携版 exe**（拷到哪都能运行，卸载即删文件夹）
3. 目标机**已装 Python**（但很可能未安装 flask/paramiko，故后端需自包含）
4. **关窗即退出**：关闭窗口时停止 SSH 服务和后端进程

### 已确认决策

| 决策点 | 选择 |
|---|---|
| 重构方案 | 方案 A：Electron 外壳 + Python 后端（PyInstaller 打成自包含 exe） |
| 后端依赖 | PyInstaller 打包，不依赖目标机任何 pip 包 |
| 分发形式 | electron-builder portable 单文件 exe |
| 关窗行为 | 关窗即退出（kill 后端进程树） |
| 数据目录 | config.json / host_key 存于 exe 同级目录（随 exe 走） |

## 2. 架构总览

```
SmartKit-Simulator.exe  ← electron-builder portable 单文件（双击自解压运行）
│
├── Electron 主进程 (electron/main.js)
│     ├── spawn 后端进程（dev=python，prod=resources\backend\simulator_gui.exe）
│     ├── 解析 stdout 就绪信号 "SMARTKIT_READY_PORT=<port>" → 打开 BrowserWindow
│     ├── 加载 http://127.0.0.1:<port>（index.html + 全部 /api/* 由 Flask 提供，零改动）
│     ├── 关窗/退出时 taskkill /pid <pid> /T /F 杀后端进程树
│     └── 后端崩溃 → 错误对话框 + 退出
│
├── 后端进程 simulator_gui.exe（PyInstaller --onefile）
│     ├── Flask: 原 index.html + 全部 API 路由（不改）
│     ├── Paramiko: SSH 服务（不改）
│     └── 新增 --headless 模式：不弹浏览器，绑定后打印就绪信号
│
└── 运行时数据（config.json / host_key）
      └── exe 同级目录（PORTABLE_EXECUTABLE_DIR 定位，dev 时为项目根目录）
```

**核心原则**：Python 侧 SSH 逻辑与前端 `index.html` 零改动；Electron 只负责进程编排与窗口承载。

## 3. Python 后端改动（simulator_gui.py）

### 3.1 新增命令行参数

| 参数 | 类型 | 作用 |
|---|---|---|
| `--headless` | flag | 不调用 `webbrowser.open()`；不预选 5800-5899 端口 |
| `--data-dir <path>` | str | 覆盖 config.json / host_key 的读写目录（默认仍为脚本目录） |

### 3.2 启动流程改造

- 由 `app.run(host, port)` 改为 `werkzeug.serving.make_server("127.0.0.1", 0, app)`：
  - 绑定成功后从 `server.server_port` 读取系统分配的实际端口
  - **端口 0 + 读取真实端口**，天然规避端口冲突竞态，无需预扫描
- 绑定成功后向 stdout 打印一行机器可解析信号：

  ```
  SMARTKIT_READY_PORT=61234
  ```

- 非 headless 模式保持现状（自动开浏览器、5800-5899 扫描），保证 CLI 兼容。

### 3.3 数据目录适配（PyInstaller）

PyInstaller `--onefile` 下 `__file__` 指向 `sys._MEIPASS` 临时解压目录，不可写。需调整路径解析：

| 资源 | 来源 | 读取方式 |
|---|---|---|
| `index.html` | 打包进 bundle | `sys._MEIPASS`（`--add-data "index.html;."`） |
| `config.json`（读+写） | data-dir | `--data-dir` 指定，默认脚本目录 |
| `host_key`（生成+写） | data-dir | 同 config.json |

```python
def resource_path(relative_path):
    # index.html 等只读 bundle 资源
    base = getattr(sys, "_MEIPASS", BASE_DIR)
    return os.path.join(base, relative_path)

def writable_path(relative_path):
    # config.json / host_key 等读写资源
    return os.path.join(DATA_DIR, relative_path)
```

## 4. Electron 主进程（electron/main.js）

### 4.1 进程生命周期

```
app.whenReady()
  → 确定运行模式与后端启动命令（见 4.1.1）
  → spawn（windowsHide: true，不弹黑窗）
  → 监听 stdout 匹配 "SMARTKIT_READY_PORT=<port>"（30s 超时）
  → 创建 BrowserWindow（1280×800，contextIsolation:true, nodeIntegration:false, sandbox:true）
  → ready-to-show 后显示，加载 http://127.0.0.1:<port>
```

#### 4.1.1 运行模式与路径解析

| 模式 | 判定 | 后端命令 | data-dir |
|---|---|---|---|
| **打包（prod）** | `app.isPackaged === true` | `path.join(process.resourcesPath, "backend", "simulator_gui.exe")` | 优先 `process.env.PORTABLE_EXECUTABLE_DIR`（portable 自解压 exe 的真实所在目录）；该变量缺失时回退 `app.getPath("userData")` |
| **开发（dev）** | `app.isPackaged === false` | `path.join(app.getAppPath(), "..", ".venv", "Scripts", "python.exe") simulator_gui.py`（不存在则回退 `python`） | 项目根目录（`app.getAppPath()` 的父目录） |

注意：portable 模式下 exe 运行时会自解压到 `%TEMP%`，`process.cwd()` 与 `process.resourcesPath` 均指向临时目录，**不可写、每次运行清空**；因此数据必须落到 `PORTABLE_EXECUTABLE_DIR`（用户放置 exe 的真实目录）才能实现"配置随 exe 走"。

### 4.2 关窗即退出

- `window-all-closed` → 终止后端进程树 → `app.quit()`
- Windows 上 PyInstaller onefile 有父+子两层进程，须整树杀：

  ```javascript
  execFileSync("taskkill", ["/pid", String(backend.pid), "/T", "/F"]);
  ```

### 4.3 错误处理

| 场景 | 处理 |
|---|---|
| 后端启动失败（Python 缺失/导入错误） | 捕获 stderr，弹 MessageBox 显示原因，退出 |
| 就绪信号 30s 超时 | 弹错误框"后端启动超时"，退出 |
| 后端运行中崩溃/退出 | 弹错误框，退出（不自动重启） |
| 端口冲突 | make_server 用 port 0 自动分配，天然规避 |

### 4.4 安全基线

`contextIsolation: true`、`nodeIntegration: false`、`sandbox: true`、`webSecurity` 默认开启。前端只加载本机可信后端页面，不需要任何 Node 能力，无需 preload。

## 5. 打包

### 5.1 第一级：PyInstaller 打后端

```powershell
pyinstaller --onefile --name simulator_gui --add-data "index.html;." `
    --distpath dist/backend simulator_gui.py
# → dist/backend/simulator_gui.exe (~20MB)
```

### 5.2 第二级：electron-builder 打便携版 exe

- `electron/package.json` 配置 electron-builder：
  - target: `portable`（win）
  - `extraResources`: 将 `dist/backend/simulator_gui.exe` 复制到 `resources/backend/`
  - `productName`: SmartKit Simulator
  - portable 目标运行时提供 `PORTABLE_EXECUTABLE_DIR` 环境变量 → 定位 exe 同级数据目录
- 产物：`dist/SmartKit-Simulator-1.0.0.exe`（单文件，双击自解压运行）

### 5.3 一键打包脚本（build.ps1）

依次执行：PyInstaller 后端 → electron-builder 前端 → 输出最终便携版 exe。

## 6. 目录结构（目标态）

```
simulator/
  electron/
    package.json           # electron + electron-builder 依赖与构建配置
    main.js                # Electron 主进程
    build/                 # 应用图标等打包资源
  build.ps1                # 一键打包脚本（后端 + 前端）
  simulator_gui.py         # 微改：--headless / --data-dir / 就绪信号 / _MEIPASS 适配
  index.html               # 不改
  config.json              # 不改（运行时数据）
  server.py                # 保留（早期 CLI 版，不参与 Electron）
  requirements.txt         # 追加 pyinstaller 为构建依赖（或独立 requirements-build.txt）
  tests/
    test_simulator_gui.py  # 保留
    test_index_html.js     # 保留
    test_portability.py    # 更新：适配 --headless 参数
    test_headless.py       # 新增：就绪信号 / data-dir / API 可达
  docs/superpowers/specs/  # 本设计文档
```

## 7. 测试策略

| 测试 | 内容 | 状态 |
|---|---|---|
| `tests/test_simulator_gui.py` | SSH 服务回归 | 保留，验证 headless 改动不破坏 SSH |
| `tests/test_index_html.js` | 前端行为 | 保留 |
| `tests/test_portability.py` | 启动脚本/文档检查 | 更新：适配 --headless 参数 |
| `tests/test_headless.py` | 新增：--headless 输出就绪信号、data-dir 生效、API 可达 | 新增 |
| Electron 冒烟（手动） | 双击 exe → 窗口出现 → Start Server → ssh 连接成功 | 手动清单 |

## 8. 开发与验证流程

### 8.1 开发模式（无打包）

```powershell
# 终端 1：手动起后端
.\.venv\Scripts\python.exe simulator_gui.py --headless --data-dir .

# 终端 2：Electron 开发模式
cd electron; npm install; npm start   # main.js 检测 dev 模式自动用 python 起后端
```

### 8.2 验证清单（交付前手动执行）

1. `python -m py_compile simulator_gui.py tests/test_simulator_gui.py tests/test_portability.py tests/test_headless.py`
2. `python -m unittest tests.test_simulator_gui tests.test_headless tests.test_portability`
3. `node tests/test_index_html.js`
4. 双击最终 exe：窗口出现、无黑窗、无控制台
5. `ssh admin@127.0.0.1 -p 2222 show system general` 输出正确
6. 修改配置 → Save → 重启 SSH 服务 → 新配置生效
7. 关闭窗口 → 进程树全部退出（任务管理器确认无残留 simulator_gui.exe）
8. 配置随 exe 移动（拷贝 exe 到新目录，config 内容保留）

## 9. 非目标（Out of Scope）

- 不改写 SSH 服务逻辑（Paramiko 保留）
- 不改写前端 index.html
- 不提供系统托盘/后台驻留
- 不做自动更新
- 不迁移 server.py（CLI 旧版）到 Electron
- 不做 macOS/Linux 打包（仅 Windows）
