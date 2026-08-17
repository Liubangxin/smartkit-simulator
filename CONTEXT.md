# SmartKit Simulator

SmartKit Simulator models device-facing SSH and REST behavior for automated test execution while keeping maintained scenario data separate from runtime state.

## Language

**模拟数据集（Dataset）**:
一组完整的设备模拟场景，包含 SSH 认证与命令响应，以及 REST 路由响应，并由唯一的数据集文件持久化。
_Avoid_: 模拟器数据、配置包

**数据集文件（Dataset File）**:
完整保存一个且仅一个模拟数据集的独立文件。
_Avoid_: 配置分片、版本目录

**数据集目录（Dataset Directory）**:
模拟器扫描和维护数据集文件的可配置文件系统位置。
_Avoid_: 数据目录、配置目录

**SSH 命令（SSH Command）**:
数据集中按命令文本匹配并返回终端输出的 SSH 行为。
_Avoid_: SSH 路由、SSH 接口

**REST 路由（REST Route）**:
数据集中按 HTTP 方法与 URI 匹配并返回状态码、响应头和响应体的 REST 行为。
_Avoid_: REST 命令

**执行快照（Runtime Snapshot）**:
从某个数据集版本生成、供一次测试执行稳定使用的不可变运行数据。
_Avoid_: 当前配置、在线数据集

**数据集工作台（Dataset Workbench）**:
维护数据集及其 SSH 命令、REST 路由、文件信息和用例绑定关系的独立界面，不承担模拟协议的运行控制。
_Avoid_: 模拟器主页、配置页

**测试用例（Test Case）**:
由外部用例执行器运行、并在执行前请求一个模拟数据集的测试定义。
_Avoid_: 执行任务、数据场景

**用例目录（Case Catalog）**:
数据集工作台用于展示和绑定的测试用例元数据镜像；测试用例的权威定义仍属于外部用例执行器。
_Avoid_: 用例仓库、测试代码

**用例绑定（Case Binding）**:
一个测试用例对某个模拟数据集文件的有效引用；多个测试用例可以绑定同一个数据集。
_Avoid_: 数据集副本、用例数据
