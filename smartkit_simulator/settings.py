"""Global settings persisted in ``settings.json`` (single source of truth).

SSH/REST listener addresses, ports, SSH credentials and lease timeout live
here, never inside dataset files.  ``load_app_settings`` / ``save_app_settings``
take the ``ApplicationState`` because they need the current data directory.
"""

import socket

from .errors import WorkspaceError

DEFAULT_SERVER = {
    "bind_address": "127.0.0.1",
    "port": 2222,
    "username": "admin",
    "password": "admin123",
}
DEFAULT_REST_SERVER = {"bind_address": "127.0.0.1", "port": 8080}
DEFAULT_APP_SETTINGS = {
    "schema_version": 1,
    "management_server": {"bind_address": "127.0.0.1", "port": 35800},
    "ssh_server": {"bind_address": "127.0.0.1", "port": 2222,
                   "username": "admin", "password": "admin123"},
    "rest_server": {"bind_address": "127.0.0.1", "port": 8080},
    "lease_timeout_seconds": 1800,
}


def _service_setting(value, default, name):
    value = value if isinstance(value, dict) else {}
    bind_address = str(value.get("bind_address", default["bind_address"])).strip()
    if not bind_address:
        raise WorkspaceError(f"{name}监听地址不能为空")
    try:
        port = int(value.get("port", default["port"]))
    except (TypeError, ValueError) as error:
        raise WorkspaceError(f"{name}端口必须是整数") from error
    if not 1 <= port <= 65535:
        raise WorkspaceError(f"{name}端口必须在 1 到 65535 之间")
    return {"bind_address": bind_address, "port": port}


def local_ipv4_addresses():
    addresses = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET, socket.SOCK_STREAM):
            address = info[4][0]
            if not address.startswith("127.") and address not in addresses:
                addresses.append(address)
    except OSError:
        pass
    return addresses


def load_app_settings(state):
    workspace = state.dataset_workspace()
    stored = workspace.read_settings()
    result = dict(stored)
    result["schema_version"] = int(stored.get("schema_version", 1))
    result["dataset_directory"] = str(workspace.dataset_dir)
    for key, label in (("management_server", "管理服务"), ("ssh_server", "SSH 服务"),
                       ("rest_server", "REST 服务")):
        result[key] = _service_setting(stored.get(key), DEFAULT_APP_SETTINGS[key], label)
    stored_ssh = stored.get("ssh_server", {}) if isinstance(stored.get("ssh_server"), dict) else {}
    result["ssh_server"]["username"] = str(
        stored_ssh.get("username") or DEFAULT_APP_SETTINGS["ssh_server"]["username"]).strip()
    result["ssh_server"]["password"] = str(
        stored_ssh.get("password", DEFAULT_APP_SETTINGS["ssh_server"]["password"]))
    result["lease_timeout_seconds"] = int(
        stored.get("lease_timeout_seconds", DEFAULT_APP_SETTINGS["lease_timeout_seconds"]))
    return result


def save_app_settings(state, payload):
    current = load_app_settings(state)
    updates = {"schema_version": 1}
    for key, label in (("management_server", "管理服务"), ("ssh_server", "SSH 服务"),
                       ("rest_server", "REST 服务")):
        updates[key] = _service_setting(payload.get(key, current[key]),
                                        DEFAULT_APP_SETTINGS[key], label)
    payload_ssh = payload.get("ssh_server", {}) if isinstance(payload.get("ssh_server"), dict) else {}
    updates["ssh_server"]["username"] = str(
        payload_ssh.get("username") or current["ssh_server"]["username"]).strip()
    updates["ssh_server"]["password"] = str(
        payload_ssh.get("password", current["ssh_server"]["password"]))
    if not updates["ssh_server"]["username"]:
        raise WorkspaceError("SSH 用户名不能为空")
    try:
        lease_timeout = int(payload.get("lease_timeout_seconds",
                                        current["lease_timeout_seconds"]))
    except (TypeError, ValueError) as error:
        raise WorkspaceError("执行租约超时必须是整数") from error
    if lease_timeout <= 0:
        raise WorkspaceError("执行租约超时必须大于 0")
    updates["lease_timeout_seconds"] = lease_timeout
    state.dataset_workspace().update_settings(updates)
    return load_app_settings(state)
