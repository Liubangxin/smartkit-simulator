# 日志导入解析规格

> 适用范围：SmartKit Simulator 数据集工作台的“日志导入”功能（SSH 编辑页、REST 编辑页）。
> 解析器为纯函数，位于 `smartkit_simulator/import_logs/`；导入前一律先预览、再确认写入数据集，预览不会修改数据集文件。

本规格说明模拟器支持的两种执行日志解析格式：

1. **SSH 执行日志** → 解析为 SSH 命令及响应（支持同命令多次执行合并为有序输出）。
2. **REST 路由日志** → 解析为 REST 路由候选（支持 Redfish 与 HttpSession 两种风格）。

两种解析共用同一套日志通用约定（线程标识、日志级别、行尾元数据）。

---

## 1. 日志通用约定

测试执行器（如 Java 连接层 `SshConnection` / `HttpSession` / `RestConnection`）捕获的日志通常形如：

```text
2026-08-17 19:00:00:001 [INFO] <事件内容> (类.java:行号) [线程名](pid-进程号)
```

解析约定：

- **线程标识**：取一行中最后一个方括号片段 `[线程名]`，忽略 `[INFO]`/`[WARN]`/`[ERROR]`/`[DEBUG]` 级别片段；`(pid-N)` 可选。用于跨线程交错日志的配对。
- **时间戳前缀**：SSH 响应正文的边界依赖以 `YYYY-MM-DD` 开头的日志行，粘贴日志时**保留每行时间戳**。
- 行尾元数据（类名+行号、线程、pid）是配对的依据；SSH 响应正文中的此类元数据会被清洗。
- 提示符形如 `xxx:/>`（不限于 `admin:/>`）都会被识别并清洗。

---

## 2. SSH 执行日志解析

### 2.1 命令识别：`Execute command line`

命令行格式：

```text
Execute command line : <命令>, timeout is : <超时秒数>
```

识别规则：

- 命令名取 `Execute command line :` 之后、`, timeout is : <数字>` 之前的内容（允许时间戳/级别等前缀）。
- **必须带有 `, timeout is : <数字>` 后缀**才会被识别为一次命令执行。
- 每次匹配产生一个“执行记录”，按日志中出现位置排序。

示例（两个命令、三个执行记录）：

```text
2026-08-17 19:00:00:001 [INFO] Execute command line : show alarm, timeout is : 30 (SshConnection.java:873) [thread-a](pid-1)
2026-08-17 19:00:00:003 [INFO] Execute command line : show alarm, timeout is : 30 (SshConnection.java:873) [thread-a](pid-1)
2026-08-17 19:00:00:005 [INFO] Execute command line : show alarm, timeout is : 30 (SshConnection.java:873) [thread-a](pid-1)
2026-08-17 19:00:00:006 [INFO] Execute command line : show disk, timeout is : 30 (SshConnection.java:873) [thread-a](pid-1)
```

### 2.2 响应识别：`Receive str`

响应块以一行 `[级别] Receive str : <命令回显>` 开始：

```text
2026-08-17 19:00:00:002 [INFO] Receive str : show alarm
<响应正文第一行>
...
<响应正文最后一行>
```

边界规则：

- `Receive str :` 后的同段文本用于关联命令（通常与 `Execute command line :` 的命令名一致）。
- **响应正文从 `Receive str` 的下一行开始，持续到“下一行以 `YYYY-MM-DD` 开头且包含日志级别”的日志行，或文本结尾**。
- 因此每个命令执行后都应跟随一条带时间戳的日志行（可以是下一条 `Execute command line` 或别的日志），否则响应块会吞掉后续内容。

### 2.3 输出清洗

对每条响应正文按顺序执行以下清洗：

1. 统一换行为 `\n`，按行拆分。
2. 从**最后一个非空行**移除行尾的 Java 元数据帧：`(类.java:数字) [线程](pid-N)`（通常是提示符行）。
3. 若该行为提示符（整行匹配 `xxx:/>`，如 `admin:/>`），删除提示符行及**其后**的空行（日志记录间的捕获边界，不属于设备输出）。
4. 若**首个非空行**与命令名相同（命令回显），删除该行；回显之前的空行保留。
5. 重新拼接。

保留规则：

- **响应输出内部的空行原样保留**——包括回显行之前的空行、内容行之间的空行、以及提示符之前的尾部空行。
- **每行的行尾空格原样保留**，不再 `rstrip` / 整体 `strip`。
- 仅删除：命令回显行、`xxx:/>` 提示符行及其后空行、行尾 Java 元数据帧。

效果示例——原始响应（回显行之前有 1 个空行，`show alarm` 与 `Critical alarm detected` 行尾带空格）：

```text
Receive str : show alarm
(空行)
show alarm     
Critical alarm detected   
admin:/> (SshConnection.java:1513) [thread-a](pid-1)
```

清洗后保留为：`(空行)` + `Critical alarm detected   `（删除回显行 `show alarm     `、提示符行 `admin:/> (...)`；保留首部空行与 `Critical alarm detected` 的行尾空格）。

`Unknown command` 等失败响应**不在清洗范围内**，会原样保留为命令输出，便于复现真实失败行为。

### 2.4 线程配对与多次执行合并

- 每个 `Receive str` 块会配对到一条“执行记录”，条件：
  1. 命令名一致；
  2. 执行位置早于该响应；
  3. 该执行还没有响应；
  4. 优先配对同一线程；同线程内取位置最近的一条。
- **同命令多次执行合并为一条命令记录**：`outputs` 数组按日志顺序保存各次响应；某次执行没有捕获到响应时，该位置填入空串 `""` 占位（仍可导入）。
- 为兼容旧消费方，返回记录同时携带 `output` 字段，镜像 `outputs[0]`。
- 新命令的 `description` 默认为 `从日志导入`，`group` 为空。

### 2.5 完整示例

输入日志：

```text
2026-08-17 19:00:00:001 [INFO] Execute command line : show alarm, timeout is : 30 (SshConnection.java:873) [thread-a](pid-1)
2026-08-17 19:00:00:002 [INFO] Receive str : show alarm
show alarm
Critical alarm detected
admin:/> (SshConnection.java:1513) [thread-a](pid-1)
2026-08-17 19:00:00:003 [INFO] Execute command line : show alarm, timeout is : 30 (SshConnection.java:873) [thread-a](pid-1)
2026-08-17 19:00:00:004 [INFO] Receive str : show alarm
No alarm
2026-08-17 19:00:00:005 [INFO] Execute command line : show alarm, timeout is : 30 (SshConnection.java:873) [thread-a](pid-1)
2026-08-17 19:00:00:006 [INFO] Execute command line : show disk, timeout is : 30 (SshConnection.java:873) [thread-a](pid-1)
2026-08-17 19:00:00:007 [INFO] Receive str : show disk
show disk
Disk OK
admin:/> (SshConnection.java:1513) [thread-a](pid-1)
```

解析结果（两条命令；`show alarm` 执行三次，第三次无响应 → 空串占位）：

| 命令 | outputs | output |
| --- | --- | --- |
| `show alarm` | `["Critical alarm detected", "No alarm", ""]` | `Critical alarm detected` |
| `show disk` | `["Disk OK"]` | `Disk OK` |

再例如**线程交错 + 未知命令**的日志：

```text
2026-08-17 19:00:00:001 [INFO] Execute command line : alpha, timeout is : 30 [thread-a](pid-1)
2026-08-17 19:00:00:002 [INFO] Execute command line : beta, timeout is : 30 [thread-b](pid-2)
2026-08-17 19:00:00:003 [INFO] Receive str : beta
beta-output
admin:/> (SshConnection.java:1513) [thread-b](pid-2)
2026-08-17 19:00:00:004 [INFO] Receive str : alpha
alpha-output
admin:/> (SshConnection.java:1513) [thread-a](pid-1)
2026-08-17 19:00:00:005 [INFO] Execute command line : show version, timeout is : 30 [thread-a](pid-1)
2026-08-17 19:00:00:006 [INFO] Receive str : show version
show version
Unknown command: show version
Type 'help' for available commands.
admin:/> (SshConnection.java:1513) [thread-a](pid-1)
```

解析结果：

| 命令 | outputs |
| --- | --- |
| `alpha` | `["alpha-output"]` |
| `beta` | `["beta-output"]` |
| `show version` | `["Unknown command: show version\nType 'help' for available commands."]` |

### 2.6 预览状态与汇总

预览按**去重后的命令名**逐条给出状态（`POST /api/ssh/import-log/preview`）：

- `ready`：命令在目标数据集中不存在（且本次预览中首次出现）。
- `duplicate`：命令已存在于目标数据集（可显式选中覆盖）。

SSH 侧没有 `missing_response`——缺失响应已由空串占位，仍可导入。`summary` 字段：

| 字段 | 含义 |
| --- | --- |
| `total` | 去重后的命令条数 |
| `importable` | `ready` 条数 |
| `duplicate` | `duplicate` 条数 |
| `incomplete` | 信息性计数：`outputs` 含空串的命令条数（不影响导入） |

上例日志的汇总：`total = 2, importable = 2, duplicate = 0, incomplete = 1`（`show alarm` 含一个空输出）。

---

## 3. REST 路由日志解析

### 3.1 Redfish 风格

请求与响应以 `##url` / `##method` / `##result` 标记：

```text
##url : <URL 或路径> ##method : <HTTP 方法>
##result : <JSON>
```

- `##url ... ##method ...`：创建一条待配对请求（同一行内）。
- `##result : <JSON>`：完成**同一线程**上待配对的请求，保存 JSON 响应体。
- `##result` 的值**可以是跨行 JSON**，JSON 之后的行尾元数据用于线程配对。

### 3.2 HttpSession 风格

```text
Sending <METHOD> request to <URL> ...
Received <METHOD> response successfully from <URL>. (类.java:行号) [线程](pid-N)
ResponseInfo : <JSON>
```

事件语义：

- `Sending <METHOD> request to <URL>`：创建一条待配对请求（`...` 可选）。
- `Received <METHOD> response successfully from <URL>...`：完成请求，记录“已收到成功响应”。
- `ResponseInfo : <JSON>`：更新**同一线程最近完成**路由的响应体。

实现注意（已按解析器实际行为验证）：

- HTTP 方法匹配不区分大小写，保存时统一转为大写。
- **`Received` 行在 URL 之后必须带有以 `(` 开头的行尾元数据段**（例如 `(HttpSession.java:611) [http-nio-exec-6](pid-25320)`），否则该事件不会完成请求——粘贴真实日志时请保留行尾元数据。
- `ResponseInfo` 必须是合法 JSON；无法解析的 `ResponseInfo` 被忽略，不影响已完成的路由。

### 3.3 URI 归一化

- 完整 URL 只保留**路径部分**：协议、主机、端口、查询参数全部丢弃；解析后无路径时使用 `/`。
- 例如 `https://127.0.0.1:443/rest/plat/smapp/v1/sessions` → `/rest/plat/smapp/v1/sessions`。
- 路由 `status_code` 默认 `200`，`group` 为空。

### 3.4 配对与响应默认值

每个线程维护**一条**待配对请求：

1. 新请求覆盖该线程旧的待配对请求（旧请求若无响应则成为 `missing_response`）。
2. `Received` 必须与待配对请求的 **HTTP 方法 + URI 完全一致**，配对成功则关闭该请求：
   - 只有 `Received`、没有 `ResponseInfo` → 响应体 `{}`，无响应头。
   - 之后同线程出现合法 `ResponseInfo` → 响应体为该 JSON（`indent=2` 格式化），响应头加 `Content-Type: application/json`。
3. Redfish 的 `##result` 直接完成待配对请求：响应体为格式化 JSON，响应头加 `Content-Type: application/json`。
4. 从未完成的请求 → 状态 `missing_response`，**不能导入**。

### 3.5 完整示例

HttpSession 风格输入：

```text
2026-08-18 10:24:46:392 [INFO] Sending PUT request to https://127.0.0.1:443/rest/plat/smapp/v1/sessions ...  (HttpSession.java:606) [http-nio-exec-6](pid-25320)
2026-08-18 10:24:46:435 [INFO] Received PUT response successfully from https://127.0.0.1:443/rest/plat/smapp/v1/sessions. (HttpSession.java:611) [http-nio-exec-6](pid-25320)
2026-08-18 10:24:46:520 [INFO] Sending GET request to https://127.0.0.1:443/rest/productmgmt/v1/system-info ...  (HttpSession.java:606) [http-nio-exec-6](pid-25320)
2026-08-18 10:24:46:540 [INFO] Received GET response successfully from https://127.0.0.1:443/rest/productmgmt/v1/system-info. (HttpSession.java:611) [http-nio-exec-6](pid-25320)
2026-08-18 10:24:46:542 [INFO] ResponseInfo : {"a":"1"} (RestConnection.java:837) [http-nio-exec-6](pid-25320)
```

解析结果（两条候选路由）：

| HTTP 方法 | URI | 响应体 | 响应头 |
| --- | --- | --- | --- |
| `PUT` | `/rest/plat/smapp/v1/sessions` | `{}` | （空） |
| `GET` | `/rest/productmgmt/v1/system-info` | `{\n  "a": "1"\n}` | `Content-Type: application/json` |

Redfish 风格输入（跨行 JSON）：

```text
2026-08-15 15:42:05:685 [INFO] ##url : /redfish/v1/Chassis ##method : GET ##ip : 127.0.0.1 (RedfishConnestion.java:541) [http-nio-exec-9](pid-3240)
2026-08-15 15:42:05:700 [INFO] ##result : {
  "@odata.id": "/redfish/v1/Chassis",
  "Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]
} (RedfishConnestion.java:761) [http-nio-exec-9](pid-3240)
2026-08-15 15:42:05:704 [INFO] ##url : /redfish/v1/Chassis/1 ##method : GET ##ip : 127.0.0.1 (RedfishConnestion.java:541) [http-nio-exec-9](pid-3240)
```

解析结果：

| 状态 | HTTP 方法 | URI | 响应体 |
| --- | --- | --- | --- |
| `ready` | `GET` | `/redfish/v1/Chassis` | 格式化后的 `##result` JSON |
| `missing_response` | `GET` | `/redfish/v1/Chassis/1` | 无（未收到响应） |

### 3.6 预览状态与汇总

`POST /api/rest/import-log/preview` 按“HTTP 方法 + URI”对每条候选路由给出状态：

- `ready`：有响应且目标数据集无同“方法 + URI”路由。
- `duplicate`：有响应但“方法 + URI”已存在（可显式选中覆盖）。
- `missing_response`：没有配对到成功响应（**不能导入**）。

`summary` 字段：

| 字段 | 含义 |
| --- | --- |
| `total` | 候选路由条数 |
| `importable` | `ready` 条数 |
| `duplicate` | `duplicate` 条数 |
| `incomplete` | `missing_response` 条数 |

---

## 4. 预览接口

两个预览接口均在解析后返回带状态的结果；前端勾选 `ready`（及用户显式选中的 `duplicate`）项后，以一次数据集更新写回。

### 4.1 `POST /api/ssh/import-log/preview`

请求：

```json
{ "dataset_id": "ssh-logs", "log_text": "<粘贴的 SSH 执行日志>" }
```

`dataset_id` 可省略（无既有命令，全部按 `ready` 判定）。响应：

```json
{
  "status": "ok",
  "summary": { "total": 2, "importable": 2, "duplicate": 0, "incomplete": 1 },
  "commands": [
    {
      "status": "ready",
      "message": "Ready to import.",
      "command": {
        "name": "show alarm",
        "description": "从日志导入",
        "group": "",
        "outputs": ["Critical alarm detected", "No alarm", ""],
        "output": "Critical alarm detected"
      }
    }
  ]
}
```

### 4.2 `POST /api/rest/import-log/preview`

请求：

```json
{ "dataset_id": "rest", "log_text": "<粘贴的 REST 路由日志>" }
```

响应：

```json
{
  "status": "ok",
  "summary": { "total": 1, "importable": 1, "duplicate": 0, "incomplete": 0 },
  "routes": [
    {
      "status": "ready",
      "message": "Ready to import.",
      "route": {
        "method": "GET",
        "uri": "/rest/productmgmt/v1/system-info",
        "group": "",
        "status_code": 200,
        "response_headers": { "Content-Type": "application/json" },
        "response_body": "{\n  \"a\": \"1\"\n}"
      }
    }
  ]
}
```

### 4.3 错误

| 情况 | 状态码 |
| --- | --- |
| `log_text` 为空 | `400` |
| 指定的数据集不存在 | `404` |
| 数据集目录不可用等其他工作区错误 | `400` |

---

## 5. 注意事项

- 粘贴的日志请保留**时间戳前缀与行尾线程/pid 元数据**：SSH 响应边界、两类解析的线程配对都依赖它们。
- SSH 响应正文中的提示符 `xxx:/>`、命令回显和 Java 元数据会被自动清洗，输出内部的空行与行尾空格会保留；`Unknown command` 等真实失败输出会保留。
- SSH 同命令多次执行自动合并为有序 `outputs`，缺失响应以空串占位，仍可导入。
- REST `Received` 必须与请求的方法和 URI 一致，且行尾需带 `(...)` 元数据；URL 只保留路径。
- 导入前请先预览；预览**不会修改**数据集，确认后才写入。

## 6. 相关实现与文档

- 实现位置：`smartkit_simulator/import_logs/ssh_parser.py`、`smartkit_simulator/import_logs/rest_parser.py`、`smartkit_simulator/import_logs/common.py`
- 预览接口：`smartkit_simulator/api/import_logs.py`
- 回归测试：`tests/test_dataset_api.py`（SSH 预览）、`tests/test_e2e_multi_output.py`（合并后回放）、`tests/test_rest_simulator.py`（REST 预览）
- 相关文档：[同命令多输出设计](simulator-command-multi-outputs.md)、[REST 路由日志导入格式扩展](rest-log-import-formats.md)
