SmartKit Storage Simulator
==========================

基于 Python 的本地 SSH 服务，模拟一台存储设备的管理界面。通过标准 SSH 协议连接后，可以像操作一台真实的网络存储设备一样执行管理命令。


## 快速开始

```powershell
# 启动服务
.\run.ps1

# 另一个终端，直接执行命令
ssh admin@127.0.0.1 -p 2222 show system.general

# 或进入交互式 Shell
ssh admin@127.0.0.1 -p 2222
```

**默认凭据：** 用户名 `admin`，密码 `admin123`


## 命令参考

| 命令 | 说明 |
|---|---|
| `show system.general` | 显示系统通用信息（设备名、型号、固件、运行时间、资源使用等） |
| `help` | 显示可用命令列表（仅交互模式） |
| `exit` / `quit` | 退出当前会话（仅交互模式） |


## 配置

在 [server.py](server.py) 顶部修改以下变量：

```python
HOST = "127.0.0.1"   # 监听地址
PORT = 2222          # 监听端口
USERNAME = "admin"   # 登录用户名
PASSWORD = "admin123" # 登录密码
```

首次启动会自动生成 `host_key`（RSA 2048 位），无需手动配置。


## 架构

```
客户端                 服务端
──────                ──────
ssh 连接    ──────►   socket.accept()
                      └── 每条连接分配独立线程
                          └── paramiko.Transport（SSH 握手 + 加密）
                              └── StorageSimulatorServer（认证 + 命令路由）
                                  ├── exec_command → handle_exec()
                                  └── shell 会话   → handle_shell()
```

- **传输层**：paramiko 处理 SSH 协议协商、加密、通道管理
- **认证层**：`check_auth_password` 拦截密码验证
- **通道层**：`check_channel_shell_request` / `check_channel_exec_request` 分派到对应处理函数
- **并发**：每个客户端连接一个独立线程，互不阻塞


## 依赖

- Python 3.12+
- [paramiko](https://www.paramiko.org/) 5.0+

```powershell
pip install paramiko
```


## 输出示例

```
$ ssh admin@127.0.0.1 -p 2222 show system.general

System General Information
==========================
Device Name:    SmartKit Storage Simulator
Model:          SK-2000
Firmware:       v2.3.1 (Build 20260714)
Serial Number:  SK20260714001
System Uptime:  0 days, 2 hours, 15 minutes
System Time:    2026-07-14 15:00:00 CST
CPU Usage:      12%
Memory:         4096 MB total, 1024 MB used, 3072 MB free
Storage Pools:  2
Volumes:        5
Network:        eth0: 192.168.1.100/24
```
