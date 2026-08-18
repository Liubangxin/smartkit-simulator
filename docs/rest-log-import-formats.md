# REST 路由日志导入格式扩展

## 背景

REST 路由日志导入原先只支持 Redfish 风格的 `##url` 和 `##result` 日志。例如：

```text
##url : /redfish/v1/Chassis ##method : GET
##result : {"Members": []}
```

部分设备管理组件使用 `HttpSession` 输出请求和响应日志，格式如下：

```text
Sending PUT request to https://127.0.0.1:443/rest/plat/smapp/v1/sessions ...
Received PUT response successfully from https://127.0.0.1:443/rest/plat/smapp/v1/sessions.

Sending GET request to https://127.0.0.1:443/rest/productmgmt/v1/system-info ...
Received GET response successfully from https://127.0.0.1:443/rest/productmgmt/v1/system-info.
ResponseInfo : {"a":"1"}
```

本次扩展让导入功能同时支持两种格式，并保持原有导入行为兼容。

## 解析结果

上述 `HttpSession` 日志会生成两条候选路由：

| HTTP 方法 | URI | 响应体 |
| --- | --- | --- |
| `PUT` | `/rest/plat/smapp/v1/sessions` | `{}` |
| `GET` | `/rest/productmgmt/v1/system-info` | `{"a":"1"}` |

URL 解析时只保留路径部分，协议、主机、端口和查询参数不会进入路由 URI。

## 支持的事件

解析器将日志转换成按位置排序的事件，再按线程配对。

### 原有 Redfish 格式

- `##url : <URL> ##method : <METHOD>`：创建待匹配请求。
- `##result : <JSON>`：完成同线程中的待匹配请求，并保存 JSON 响应。

### 新增 HttpSession 格式

- `Sending <METHOD> request to <URL>`：创建待匹配请求。
- `Received <METHOD> response successfully from <URL>`：完成同线程中方法和路径均一致的请求。
- `ResponseInfo : <JSON>`：更新同线程最近完成路由的响应体。

HTTP 方法匹配不区分大小写，保存时统一转换为大写。

## 请求与响应配对

每条日志通过末尾的线程标识进行关联，例如：

```text
[http-nio-127.0.0.1-8089-exec-6](pid-25320)
```

配对规则如下：

1. 每个线程维护一条待完成请求。
2. `Received` 事件必须与待完成请求的 HTTP 方法和 URI 一致。
3. 不同线程的交错日志互不影响。
4. `ResponseInfo` 只更新同线程最近完成的路由。
5. 请求日志只从 `Sending` 事件创建，`Received` 不会重复创建路由。

## 响应默认值

`HttpSession` 日志不一定输出响应体。为了让已记录成功响应的路由可以直接导入：

- 只有 `Received`、没有 `ResponseInfo` 时，响应体使用 `{}`，响应头为空。
- 存在合法 JSON `ResponseInfo` 时，使用格式化后的 JSON 作为响应体，并增加 `Content-Type: application/json`。
- 没有匹配到成功响应的请求仍标记为 `missing_response`，不能默认导入。
- 无法解析为 JSON 的 `ResponseInfo` 会被忽略，不会破坏已完成路由。

## 重复路由处理

导入预览继续按“HTTP 方法 + URI”识别重复路由。新格式不会改变已有规则：

- 新路由标记为 `ready`。
- 已存在的路由标记为 `duplicate`。
- 用户显式选择重复项时，可以覆盖原有路由配置。

## 实现位置

- 解析入口：`simulator_gui.py` 中的 `parse_rest_routes_from_log`
- 预览接口：`POST /api/rest/import-log/preview`
- 回归测试：`tests/test_rest_simulator.py` 中的 `test_log_import_extracts_http_session_sending_and_received_format`

## 验证

REST 模拟器测试集包含原有 Redfish 格式、线程交错配对和新增 `HttpSession` 格式的回归测试。当前共 17 项测试通过。
