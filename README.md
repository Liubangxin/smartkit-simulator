# SmartKit Storage Simulator

SmartKit Storage Simulator 是一个本地 SSH 存储设备模拟器。它使用 Python、Flask 和 Paramiko 提供 Web 图形界面，可配置 SSH 登录信息和命令输出，用于模拟存储设备 CLI 命令返回。

## 功能概览

- Web GUI 管理 SSH 服务端口、用户名和密码。
- 支持配置 SSH 服务监听地址，默认 `127.0.0.1`，也可以改为 `0.0.0.0` 允许通过本机实际 IP 访问。
- 支持新增、删除、编辑模拟命令。
- 命令名称不允许重复。
- 命令编辑器默认只读，点击 **Edit** 后才能修改；进入编辑后按钮变为 **Cancel**。
- 点击 **Save Command** 后保存到 `config.json`。
- SSH 服务运行期间会读取最新命令配置。
- 支持 Stop -> Start 重启服务，并确保旧服务停止后再启动新服务。
- 底部日志面板可上下拖动调整高度。
- 命令输出自动统一为 CRLF，避免 PowerShell / SSH 终端多行输出错位。

## 开发环境配置

建议在项目根目录创建 Python 虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

如果 PowerShell 阻止执行脚本，可以在当前终端临时放开执行策略：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 启动 GUI

推荐使用启动脚本：

```powershell
.\start_gui.ps1
```

`start_gui.ps1` 会优先使用项目目录下的 `.venv\Scripts\python.exe`。如果没有创建虚拟环境，会继续尝试系统中的 `python` 或 `py -3`。

也可以直接运行：

```powershell
python .\simulator_gui.py
```

启动后访问：

```text
http://127.0.0.1:5800
```

如果 `5800` 被占用，程序会自动尝试 `5801` 到 `5899` 范围内的可用端口。

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
  simulator_gui.py        Flask Web GUI 和可配置 SSH 服务
  index.html              GUI 页面
  config.json             服务配置和命令输出配置
  requirements.txt        Python 运行依赖
  start_gui.ps1           GUI 开发启动脚本
  server.py               CLI SSH 模拟服务
  run.ps1                 CLI 启动脚本
  tests/
    test_simulator_gui.py SSH 服务端回归测试
    test_index_html.js    前端行为测试
    test_portability.py   启动脚本和文档检查
  README.md
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

- Python 3.12+
- Flask >= 3.0
- Paramiko >= 5.0
- Node.js，仅运行前端测试时需要

## 注意事项

- `.venv/` 是本地虚拟环境目录，不应提交到 Git。
- `config.json` 会保存 SSH 用户名、密码和命令输出配置。
- `config.json` 中的 `server.bind_address` 控制 SSH 服务监听地址。
- 本工具面向本地模拟测试使用，默认监听 `127.0.0.1`。
- 如果端口被占用，GUI 日志区会显示绑定端口失败信息。
