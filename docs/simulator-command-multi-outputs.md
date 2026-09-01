# 同命令多输出（有序序列）设计

> 状态：已实现（2026-08-31）  
> 决策：round-robin 循环 · 每连接独立计数 · 缺失输出空串占位 · `output` 镜像 `outputs[0]`

## 1. 需求

测试执行日志中，同一条 SSH 命令可能被执行多次，且每次输出不同（例如 `show alarm` 先返回告警、清除后返回空）。模拟器回放时应按捕获顺序返回对应输出：**同一输入，多个有序输出**。

## 2. 数据模型（schema 扩展，向后兼容）

```json
{
  "name": "show alarm",
  "description": "查询当前告警",
  "group": "Alarm",
  "output": "Critical alarm detected",
  "outputs": ["Critical alarm detected", "No alarm", "Alarm cleared"]
}
```

- `outputs`（新增、可选）：有序 string 数组，顺序即执行顺序。
- `output`（保留）：单输出兼容形式。`outputs` 为空/缺省时行为与旧版完全一致。
- **冗余镜像**：规范化（`DatasetWorkspace._normalize_command`）时若 `outputs` 非空，将 `output` 同步为 `outputs[0]`，只读 `output` 的旧逻辑看到首个输出。
- 校验：`outputs` 必须是 string 数组，否则 `400`；空数组按"未配置"处理（丢弃该键）。
- 取值优先级：`outputs` 非空 → 用它；否则 `output`（存在即用，含空串）；两者皆无 → 空输出。

## 3. 运行时序列语义

- **步进策略：round-robin 循环**。第 k 次执行返回 `outputs[k % n]`；确定性、有界，日志前 N 次精确复现，后续可预测。
- **计数范围：每连接独立**。计数器挂在连接级 `SimulatorServer` 实例（`_output_index`，按命令名记下标）；同一连接的 Shell 交互与 Exec 调用共享计数；新连接从序列头部开始，并发会话互不干扰。
- 变量替换（`{date}`/`{sn}` 等）对每个输出照常生效；序列中的空串按序返回（`format_command_output("")` → 空行），与"设备执行了命令但无输出"语义一致。
- 无匹配命令仍返回 `Unknown command`；`help` 列表、认证逻辑不变。

## 4. 日志导入

- 解析（`parse_ssh_commands_from_log`）：按命令名分组合并，`outputs` 按日志出现顺序排列；某次执行无响应（无 `Receive str`）时该位填入 `""`，**照常导入**（决策：缺失输出空串占位）。返回的命令同时携带 `output`（镜像 `outputs[0]`）兼容旧消费方。
- 预览状态（`/api/ssh/import-log/preview`）：
  - 命令名不存在 → `ready`
  - 命令名已存在 → `duplicate`（可显式选中覆盖，沿用现有机制）
  - `missing_response` 状态不再产生（空输出已占位导入）
- summary：`total` 按去重后的命令名计数；`incomplete` 为信息性计数——"序列中含空输出的命令数"（不影响导入）。
- 确认导入：选中项以 `{...command, group}` 展开写入数据集，`outputs` 随命令保存。

## 5. 前端（workbench.html）

- SSH 命令编辑器：
  - 无 `outputs`（或长度 ≤1）：单个输出 textarea + "＋ 添加输出变体"按钮。
  - 有 `outputs`（长度 >1）：有序序列编辑器（每项一个 textarea，带序号、上移/下移/删除），底部"＋ 添加输出变体"。
  - 保存：序列模式收集各 textarea 为 `outputs` 并镜像 `output`；单输出模式写 `output` 并删除 `outputs` 键。
- 运行快照只读视图：复用同一表单（禁用态），序列完整展示。
- 日志导入预览："输出摘要"列展示序列（`1.xxx 2.xxx`，空项显示"（空）"）；汇总文案改为"含空输出 N"。

## 6. 契约与兼容

- 纯 schema 加法扩展：现有 API 路径/响应结构、revision/原子写、导出导入均不变；旧数据集文件无需迁移。
- SSH 协议行为仅在 `outputs` 存在时改变；未配置 `outputs` 的命令行为与旧版完全一致（现有测试基线保持全绿）。
- REST 路由不在本次范围（`rest_routes` 已有 method+uri 键；REST 多输出留作后续扩展）。

## 7. 测试覆盖

- 单元（test_simulator_gui.py）：同一连接内同命令多次执行按序循环；单输出命令重复执行不变；新连接从序列头部开始（连接隔离）。
- 数据集规范化（test_dataset_api.py）：`outputs` 保存、`output` 镜像、空数组丢弃、非字符串数组返回 400。
- 日志导入（test_dataset_api.py）：同命令多次输出合并为有序 `outputs`；无响应实例空串占位且可导入；summary 按去重命令名计数。
- 前端（test_production_ui.js）：导入命令携带 `outputs`；序列编辑器逐项渲染与保存 payload 有序；`output` 镜像；新增变体渲染新 textarea。
