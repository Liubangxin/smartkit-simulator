# SmartKit Simulator

## 项目是什么

SmartKit Simulator 是一个面向自动化测试和设备联调的本地存储设备模拟器。它通过数据集（Dataset）提供可配置的 SSH 命令响应和 REST HTTPS 路由响应，让测试用例在没有真实存储设备时也能稳定复现正常、异常和边界场景。

核心组成：

- Python 后端：Flask 管理 API、SSH 模拟服务、REST HTTPS 模拟服务、数据集与运行快照管理。
- Web 前端：单文件 HTML/CSS/JS 实现的数据集工作台与模拟器运行界面。
- Electron Windows 桌面外壳：负责启动和关闭 Python 后端，并打包为便携版单文件程序。

关键行为：

- 一个数据集对应一个独立 JSON 文件，只包含 SSH 命令响应和 REST 路由响应；SSH/REST 监听配置与 SSH 认证统一保存在 `settings.json`。
- 测试执行器通过 `POST /api/runtime/activate-case` 绑定数据集并激活不可变执行快照，结束后通过 `POST /api/runtime/release` 释放。
- 同一时间只允许一个活动快照；激活后编辑数据集不影响运行中的快照。
- 数据集保存使用 `revision` 乐观锁和临时文件原子替换，冲突时返回 `409`。

## 技术栈与框架

- Python 3.12+，Windows 是主要运行平台。
- Flask 3.x：管理 API 和 REST 模拟 HTTPS 服务。
- Paramiko：SSH 模拟服务。
- cryptography：生成 REST 服务自签名 TLS 证书。
- Werkzeug：内嵌 WSGI 服务器（`make_server`）。
- 前端：原生 HTML/CSS/JS 单文件，无前端构建框架。当前生产界面是 `prototype_dataset_ui_a_full.html`，`index.html` 是早期兼容界面。
- Electron 31 + electron-builder：Windows 桌面外壳与便携版打包。
- PyInstaller：把 Python 后端打包为单个 `simulator_gui.exe`。
- 测试：Python `unittest` 覆盖后端；Node.js 脚本对前端 HTML/JS 做静态和交互测试。

## 目录结构

- `simulator_gui.py`：主后端入口，包含 Flask 管理 API、SSH/REST 模拟服务、`--headless` 与 `--data-dir` 模式。
- `dataset_workspace.py`：数据集目录扫描、单文件 JSON CRUD、原子写入、用例目录与绑定、运行快照管理。
- `prototype_dataset_ui_a_full.html`：当前生产数据集工作台和模拟器运行界面，由 `/` 路由直接返回。
- `index.html`：早期兼容界面，仍保留用于兼容性测试。
- `electron/`：Electron 外壳，启动后端并读取 `SMARTKIT_READY_PORT` 信号后打开主窗口。
- `build_backend.ps1` / `build_electron.ps1`：PyInstaller 与 Electron 打包脚本。
- `tests/`：Python `unittest` 测试与 Node.js 前端测试。
- `docs/`：架构设计和日志导入格式说明文档。
- `datasets/`：默认数据集目录，其中 `.smartkit/` 保存 `case-bindings.json` 和 `case-catalog.json`。
- `settings.json`：全局设置，包括管理/SSH/REST 端口、数据集目录和租约超时。

## 常用命令

开发运行：

```powershell
.\.venv\Scripts\python.exe .\simulator_gui.py
.\start_gui.ps1
```

默认访问 `http://127.0.0.1:35800`；端口被占用时自动选择 `35801` 到 `35899` 中的可用端口。

Headless 模式（供 Electron 外壳使用）：

```powershell
.\.venv\Scripts\python.exe .\simulator_gui.py --headless --data-dir <目录>
```

就绪后向 stdout 输出 `SMARTKIT_READY_PORT=<端口>`。

运行测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
node .\tests\test_production_ui.js
node .\tests\test_index_html.js
```

构建 Windows 桌面应用：

```powershell
.\build_backend.ps1
cd electron
npm run dist
```

## 关键约定

- 数据集 ID 创建后不可修改，文件名固定为 `<dataset_id>.json`。
- 更新数据集必须携带当前 `revision`，否则返回 `409 Conflict`。
- 工作台编辑与运行快照隔离：编辑数据集不会改变已经激活的快照。
- 全局设置持久化在 `settings.json`，不随数据集切换；SSH/REST 监听地址、端口和 SSH 用户名/密码由全局设置统一管理，数据集文件不保存服务配置。
- REST 路由按“HTTP 方法 + URI”匹配，支持 `{session_id}` 形式的单段路径参数；固定 URI 的匹配优先级高于参数化 URI。
- 默认端点：管理服务 `127.0.0.1:35800`，SSH `2222`，REST HTTPS `8080`。
- 术语定义参考 `CONTEXT.md`，详细设计参考 `docs/simulator-dataset-architecture.md`。

## 开发注意事项

- 工作区可能包含未提交的用户修改，不要回退或覆盖这些改动。
- 数据集文件 schema、管理 API 和模拟协议是外部测试执行器的契约，修改时需要保持向后兼容并同步更新测试。
- 继续使用现有模式：后端保持 Flask 路由 + `unittest`，前端保持单文件 HTML/CSS/JS，除非有充分理由引入新框架。
