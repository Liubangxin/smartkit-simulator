# SmartKit Storage Simulator

SmartKit Storage Simulator 是一个本地 SSH 存储设备模拟器。它使用 Python、Flask 和 Paramiko 提供可配置的 SSH 命令模拟，并封装为 Electron 桌面应用，可直接在 Windows 上双击 exe 运行，无需安装 Python 环境。

## 快速使用（Electron 桌面版）

直接双击 `SmartKit-Simulator-1.0.0.exe` 启动桌面应用。

便携模式下，`config.json` 和 `host_key` 保存在 exe 同级目录，方便随身携带。

## 功能概览

- **桌面应用**：Electron 封装，Windows 原生窗口，无需浏览器或 Python 环境。
- Web GUI 管理 SSH 服务端口、用户名和密码。
- 支持配置 SSH 服务监听地址，默认 `127.0.0.1`，也可以改为 `0.0.0.0` 允许通过本机实际 IP 访问。
- 支持新增、删除、编辑模拟命令。
- 命令名称不允许重复。
- 命令编辑器默认只读，点击 **Edit** 后才能修改；进入编辑后按钮变为 **Cancel**。
- 点击 **Save Command** 后保存到 `config.json`。
- SSH 服务运行期间会读取最新命令配置。
- 支持 Stop → Start 重启服务，并确保旧服务停止后再启动新服务。
- 底部日志面板可上下拖动调整高度。
- 命令输出自动统一为 CRLF，避免 PowerShell / SSH 终端多行输出错位。

## 构建 Electron 桌面版

### 前置条件

- Python 3.12+（含 pip）
- Node.js（含 npm）
- .NET Framework 4.x（C# 编译器 `csc.exe`，Windows 自带）

### 环境准备

```powershell
# 创建 Python 虚拟环境并安装依赖
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# 安装 Electron 依赖
cd electron
npm install
cd ..
```

如果 PowerShell 阻止执行脚本：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 一键构建

```powershell
.\build_electron.ps1
```

该脚本会自动完成：
1. 用 PyInstaller 编译 `simulator_gui.py` → `dist/backend/simulator_gui.exe`（15.7 MB）
2. 设置 7za 包装器（解决 winCodeSign 符号链接问题）
3. 用 electron-builder 打包为便携版 exe → `electron/dist/SmartKit-Simulator-1.0.0.exe`（83.3 MB）

### 分步构建

仅构建 Python 后端 exe：

```powershell
.\build_backend.ps1
```

仅打包 Electron（需要先完成上一步）：

```powershell
cd electron
npm run dist
```

### 构建产物

```
electron\dist\SmartKit-Simulator-1.0.0.exe   ← 双击运行
```

## 开发模式（Python 直接运行）

开发调试时不需 Electron 打包，直接启动 Flask 服务即可。

### 开发环境配置

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 启动 GUI

推荐使用启动脚本：

```powershell
.\start_gui.ps1
```

也可以直接运行：

```powershell
python .\simulator_gui.py
```

启动后访问：

```text
http://127.0.0.1:5800
```

如果 `5800` 被占用，程序会自动尝试 `5801` 到 `5899` 范围内的可用端口。

### 用 Electron 开发模式运行

```powershell
cd electron
npm start
```

此模式下 Electron 会自动查找 `.venv` 中的 Python 环境启动后端。

## 使用 GUI

1. 在顶部配置 SSH 监听地址、端口、用户名和密码。
2. 在左侧选择已有命令，或点击 **+ New** 创建命令。
3. 右侧命令编辑器默认只读，点击 **Edit** 后进入编辑模式。
4. 修改命令名称、描述或输出内容。
5. 点击 **Save Command** 保存配置。
6. 点击 **Start Server** 启动 SSH 服务。
7. 在 PowerShell 中使用 SSH 命令连接测试。

## SSH 调用示例

```powershell
ssh admin@127.0.0.1 -p 2222 show system general
```

进入交互式 Shell：

```powershell
ssh admin@127.0.0.1 -p 2222
```

默认用户名为 `admin`，默认密码为 `admin123`。

### 通过实际 IP 访问

默认监听地址是 `127.0.0.1`，只能在本机通过 `127.0.0.1` 访问：

```powershell
ssh admin@127.0.0.1 -p 2222
```

如果希望通过机器的实际 IP 访问，例如 `100.125.99.169`，请在 GUI 顶部将 **Bind** 改为：

```text
0.0.0.0
```

然后点击 **Start Server**。连接命令示例：

```powershell
ssh admin@100.125.99.169 -p 2222
```

如果连接失败，请检查 Windows 防火墙是否允许当前端口入站访问，并确认 `100.125.99.169` 是当前机器上的有效网卡 IP。

## 命令输出变量

GUI 中配置的命令输出支持以下变量，执行命令时会自动替换：

| 变量 | 说明 | 示例 |
|---|---|---|
| `{date}` | 当前日期 | 2026-07-14 |
| `{time}` | 当前时间 | 15:30:00 |
| `{datetime}` | 当前日期和时间 | 2026-07-14 15:30:00 |
| `{date_mmdd}` | 月日 | 0714 |
| `{date_yyyymmdd}` | 年月日 | 20260714 |
| `{sn}` | 随机序列号 | 9 位数字 |

## CLI 模式

也可以运行早期 CLI 版 SSH 模拟器：

```powershell
.\run.ps1
```

注意：CLI 模式使用 `server.py`，主要是早期固定命令版本。推荐使用 `simulator_gui.py` 的 Web GUI 版本。

## 项目结构

```text
simulator/
├── simulator_gui.py         Flask Web GUI 和可配置 SSH 服务（Python 后端）
├── index.html               GUI 前端页面
├── config.json              服务配置和命令输出配置
├── requirements.txt         Python 运行依赖
├── server.py                CLI SSH 模拟服务（早期版本）
│
├── electron/                Electron 桌面应用
│   ├── main.js              Electron 主进程
│   ├── package.json         Electron 依赖和打包配置
│   └── 7za_wrapper.cs       7za 包装器（构建时解决符号链接问题）
│
├── build_backend.ps1        PyInstaller 构建脚本
├── build_electron.ps1       一键构建脚本（后端 + Electron 打包）
├── start_gui.ps1            开发模式启动脚本
├── run.ps1                  CLI 模式启动脚本
│
├── tests/
│   ├── test_simulator_gui.py    SSH 服务端回归测试
│   ├── test_index_html.js       前端行为测试
│   └── test_portability.py      启动脚本和文档检查
│
├── dist/
│   └── backend/
│       └── simulator_gui.exe    PyInstaller 编译的后端 exe
│
└── README.md
```

## 测试

建议先激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

前端行为测试：

```powershell
node tests/test_index_html.js
```

Python / SSH 服务端测试：

```powershell
python -m unittest tests.test_simulator_gui
```

启动脚本和文档检查：

```powershell
python -m unittest tests.test_portability
```

Python 语法检查：

```powershell
python -m py_compile simulator_gui.py tests/test_simulator_gui.py tests/test_portability.py
```

## 依赖

**运行环境（桌面版无需安装）**：
- Python 3.12+
- Flask >= 3.0
- Paramiko >= 5.0

**构建环境**：
- PyInstaller >= 6.0（编译 Python 后端）
- Node.js + npm（Electron 打包）
- .NET Framework 4.x（`csc.exe`，Windows 自带，构建 7za 包装器）

**Electron 依赖**（`electron/package.json`）：
- electron ^31.0.0
- electron-builder ^24.13.3

## 注意事项

- `.venv/` 是本地虚拟环境目录，不应提交到 Git。
- `config.json` 会保存 SSH 用户名、密码和命令输出配置。
- `config.json` 中的 `server.bind_address` 控制 SSH 服务监听地址。
- 本工具面向本地模拟测试使用，默认监听 `127.0.0.1`。
- 如果端口被占用，GUI 日志区会显示绑定端口失败信息。
- 便携版 exe 运行时会解压到临时目录，关闭后自动清理。
- 便携版 exe 的配置数据保存在 exe 所在目录（`PORTABLE_EXECUTABLE_DIR`）。
