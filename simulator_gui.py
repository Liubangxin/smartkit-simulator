#!/usr/bin/env python3
"""SmartKit Storage Simulator - Web GUI (Flask)"""

import copy, hashlib, json, os, queue, socket, ssl, sys, threading, time, datetime, random, string, webbrowser, ipaddress, http.client, urllib.parse, re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

import paramiko
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from flask import Flask, request, jsonify, Response, send_file
from werkzeug.serving import make_server
from dataset_workspace import ConflictError, DatasetWorkspace, WorkspaceError

def resource_path(relative_path):
    base = getattr(sys, "_MEIPASS", BASE_DIR)
    return os.path.join(base, relative_path)

DATA_DIR = BASE_DIR

def writable_path(relative_path):
    return os.path.join(DATA_DIR, relative_path)

def set_data_dir(path):
    global DATA_DIR, CONFIG_PATH, HOST_KEY_PATH, REST_CERT_PATH, REST_KEY_PATH
    DATA_DIR = os.path.abspath(path)
    os.makedirs(DATA_DIR, exist_ok=True)
    CONFIG_PATH = writable_path("config.json")
    HOST_KEY_PATH = os.path.join(DATA_DIR, "host_key")
    REST_CERT_PATH = os.path.join(DATA_DIR, "rest_cert.pem")
    REST_KEY_PATH = os.path.join(DATA_DIR, "rest_key.pem")

CONFIG_PATH = writable_path("config.json")
HOST_KEY_PATH = os.path.join(DATA_DIR, "host_key")
REST_CERT_PATH = os.path.join(DATA_DIR, "rest_cert.pem")
REST_KEY_PATH = os.path.join(DATA_DIR, "rest_key.pem")
app = Flask(__name__)
log_queue = queue.Queue()
stop_event = threading.Event()
server_thread = None
server_lock = threading.Lock()
rest_server = None
rest_thread = None
rest_lock = threading.Lock()
runtime_lock = threading.Lock()
runtime_snapshot = None

DEFAULT_SERVER = {
    "bind_address": "127.0.0.1",
    "port": 2222,
    "username": "admin",
    "password": "admin123",
}
DEFAULT_REST_SERVER = {"bind_address": "127.0.0.1", "port": 8080}

def local_ipv4_addresses():
    addresses = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
            address = info[4][0]
            if not address.startswith("127.") and address not in addresses:
                addresses.append(address)
    except OSError:
        pass
    return addresses

def ensure_rest_certificate():
    if os.path.exists(REST_CERT_PATH) and os.path.exists(REST_KEY_PATH):
        return
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "SmartKit REST Simulator"),
    ])
    san_entries = [x509.DNSName("localhost"), x509.DNSName(socket.gethostname()),
                   x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    san_entries.extend(x509.IPAddress(ipaddress.ip_address(address))
                       for address in local_ipv4_addresses())
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(issuer).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
            .sign(key, hashes.SHA256()))
    with open(REST_KEY_PATH, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    with open(REST_CERT_PATH, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

def create_rest_tls_context():
    ensure_rest_certificate()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(REST_CERT_PATH, REST_KEY_PATH)
    return context

def substitute_variables(text):
    now = datetime.datetime.now()
    sn = "".join(random.choices(string.digits, k=9))
    for k, v in {"{date}": now.strftime("%Y-%m-%d"), "{time}": now.strftime("%H:%M:%S"),
                 "{datetime}": now.strftime("%Y-%m-%d %H:%M:%S"), "{date_mmdd}": now.strftime("%m%d"),
                 "{date_yyyymmdd}": now.strftime("%Y%m%d"), "{sn}": sn}.items():
        text = text.replace(k, v)
    return text

def format_command_output(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\r\n".join(text.rstrip("\n").split("\n")) + "\r\n"

def normalize_groups(config):
    for list_key, item_key in (("command_groups", "commands"), ("rest_groups", "rest_routes")):
        groups = []
        for name in config.get(list_key, []):
            name = str(name).strip()
            if name and name != "Ungrouped" and name not in groups:
                groups.append(name)
        for item in config.get(item_key, []):
            name = str(item.get("group", "")).strip()
            if name and name != "Ungrouped" and name not in groups:
                groups.append(name)
        config[list_key] = groups
    return config

def load_config():
    config_path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else resource_path("config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        config["server"] = {**DEFAULT_SERVER, **config.get("server", {})}
        config["rest_server"] = {**DEFAULT_REST_SERVER, **config.get("rest_server", {})}
        config.setdefault("commands", [])
        config.setdefault("rest_routes", [])
        return normalize_groups(config)
    return {"server": dict(DEFAULT_SERVER), "commands": [], "command_groups": [],
            "rest_server": dict(DEFAULT_REST_SERVER), "rest_routes": [], "rest_groups": []}

def save_config(config):
    config = normalize_groups(config)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def dataset_workspace():
    workspace = DatasetWorkspace(DATA_DIR)
    workspace.migrate_legacy(CONFIG_PATH)
    return workspace

def reset_runtime_state():
    global runtime_snapshot
    with runtime_lock:
        runtime_snapshot = None
    stop_event.set()

def active_config():
    with runtime_lock:
        return copy.deepcopy(runtime_snapshot["snapshot"]) if runtime_snapshot else load_config()

def _runtime_result(include_snapshot=False):
    with runtime_lock:
        if not runtime_snapshot:
            return {"status": "idle"}
        result = {key: value for key, value in runtime_snapshot.items() if key != "snapshot"}
        if include_snapshot:
            result["snapshot"] = copy.deepcopy(runtime_snapshot["snapshot"])
        return result

def _log_thread_id(text):
    matches = re.findall(r"\[([^\]\r\n]+)\](?:\(pid-[^)]+\))?", text)
    return next((value for value in reversed(matches) if value not in {"INFO", "WARN", "ERROR", "DEBUG"}), "")

def parse_rest_routes_from_log(log_text):
    """Extract ordered REST route candidates by pairing URL/result events on each log thread."""
    requests = []
    events = []
    legacy_request_pattern = re.compile(
        r"^.*?##url\s*:\s*(\S+)\s+##method\s*:\s*([A-Za-z]+).*?$", re.MULTILINE)
    http_session_request_pattern = re.compile(
        r"^.*?Sending\s+([A-Za-z]+)\s+request\s+to\s+(https?://\S+?)(?:\s+\.\.\.|\s|$).*?$",
        re.MULTILINE | re.IGNORECASE)

    request_matches = []
    for match in legacy_request_pattern.finditer(log_text):
        request_matches.append((match, match.group(1), match.group(2)))
    for match in http_session_request_pattern.finditer(log_text):
        request_matches.append((match, match.group(2), match.group(1)))

    for match, raw_url, raw_method in sorted(request_matches, key=lambda item: item[0].start()):
        method = raw_method.upper()
        parsed_url = urllib.parse.urlsplit(raw_url)
        uri = parsed_url.path or "/"
        candidate = {
            "method": method,
            "uri": uri,
            "group": "",
            "status_code": 200,
            "response_headers": {},
            "response_body": None,
        }
        requests.append(candidate)
        events.append((match.start(), "request", _log_thread_id(match.group(0)), candidate))

    decoder = json.JSONDecoder()
    for marker in re.finditer(r"##result\s*:\s*", log_text):
        body_start = marker.end()
        source = log_text[body_start:]
        leading = len(source) - len(source.lstrip())
        try:
            value, consumed = decoder.raw_decode(source.lstrip())
        except json.JSONDecodeError:
            continue
        body_end = body_start + leading + consumed
        line_end = log_text.find("\n", body_end)
        tail = log_text[body_end:line_end if line_end >= 0 else len(log_text)]
        events.append((marker.start(), "result", _log_thread_id(tail), value))

    received_pattern = re.compile(
        r"^.*?Received\s+([A-Za-z]+)\s+response\s+successfully\s+from\s+"
        r"(https?://\S+?)[.]?\s+\([^\r\n]*?$", re.MULTILINE | re.IGNORECASE)
    for match in received_pattern.finditer(log_text):
        parsed_url = urllib.parse.urlsplit(match.group(2))
        events.append((match.start(), "received", _log_thread_id(match.group(0)),
                       (match.group(1).upper(), parsed_url.path or "/")))

    response_info_pattern = re.compile(r"ResponseInfo\s*:\s*", re.IGNORECASE)
    for marker in response_info_pattern.finditer(log_text):
        source = log_text[marker.end():]
        leading = len(source) - len(source.lstrip())
        try:
            value, _consumed = decoder.raw_decode(source.lstrip())
        except json.JSONDecodeError:
            continue
        line_end = log_text.find("\n", marker.end())
        line = log_text[marker.start():line_end if line_end >= 0 else len(log_text)]
        events.append((marker.start(), "response_info", _log_thread_id(line), value))

    pending = {}
    completed = {}
    for _position, event_type, thread_id, value in sorted(events, key=lambda event: event[0]):
        if event_type == "request":
            pending[thread_id] = value
        elif event_type == "result" and thread_id in pending:
            route = pending.pop(thread_id)
            route["response_body"] = json.dumps(value, indent=2, ensure_ascii=False)
            route["response_headers"] = {"Content-Type": "application/json"}
            completed[thread_id] = route
        elif event_type == "received" and thread_id in pending:
            route = pending[thread_id]
            if (route["method"], route["uri"]) == value:
                pending.pop(thread_id)
                route["response_body"] = "{}"
                completed[thread_id] = route
        elif event_type == "response_info" and thread_id in completed:
            route = completed[thread_id]
            route["response_body"] = json.dumps(value, indent=2, ensure_ascii=False)
            route["response_headers"] = {"Content-Type": "application/json"}
    return requests

def _clean_ssh_received_output(command, body):
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        lines[-1] = re.sub(
            r"\s*\(SshConnection\.java:\d+\)\s*\[[^\]]+\](?:\(pid-[^)]+\))?\s*$",
            "", lines[-1]).rstrip()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and re.fullmatch(r"[^\r\n]*:/>\s*", lines[-1]):
        lines.pop()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[0].strip() == command:
        lines.pop(0)
    return "\n".join(lines).strip()

def parse_ssh_commands_from_log(log_text):
    """Extract SSH commands and pair multiline Receive responses from execution logs."""
    execute_pattern = re.compile(
        r"^.*?Execute command line\s*:\s*(.*?)\s*,\s*timeout is\s*:\s*\d+.*?$",
        re.MULTILINE)
    commands = []
    for match in execute_pattern.finditer(log_text):
        name = match.group(1).strip()
        commands.append({
            "position": match.start(),
            "thread_id": _log_thread_id(match.group(0)),
            "command": {"name": name, "description": "从日志导入", "group": "", "output": None},
        })

    receive_pattern = re.compile(
        r"^[^\r\n]*?\[(?:INFO|WARN|ERROR|DEBUG)\]\s+Receive str\s*:\s*([^\r\n]*)\r?\n"
        r"(.*?)(?=^\d{4}-\d{2}-\d{2}[^\r\n]*\[(?:INFO|WARN|ERROR|DEBUG)\]|\Z)",
        re.MULTILINE | re.DOTALL)
    for match in receive_pattern.finditer(log_text):
        name = match.group(1).strip()
        thread_id = _log_thread_id(match.group(0))
        eligible = [entry for entry in commands
                    if entry["position"] < match.start()
                    and entry["command"]["name"] == name
                    and entry["command"]["output"] is None]
        if thread_id:
            same_thread = [entry for entry in eligible if entry["thread_id"] == thread_id]
            if same_thread:
                eligible = same_thread
        if eligible:
            eligible[-1]["command"]["output"] = _clean_ssh_received_output(name, match.group(2))
    return [entry["command"] for entry in commands]

class SimulatorServer(paramiko.ServerInterface):
    def __init__(self, username, password, commands, command_provider=None, config_provider=None):
        self._username, self._password, self._commands = username, password, commands
        self._command_provider = command_provider or (lambda: self._commands)
        self._config_provider = config_provider

    def check_auth_password(self, username, password):
        configured = self._config_provider().get("server", {}) if self._config_provider else {}
        expected_user = configured.get("username", self._username)
        expected_password = configured.get("password", self._password)
        return paramiko.AUTH_SUCCESSFUL if username == expected_user and password == expected_password else paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_shell_request(self, channel):
        threading.Thread(target=self._handle_shell, args=(channel,), daemon=True).start()
        return True

    def check_channel_exec_request(self, channel, command):
        cmd = command.decode("utf-8").strip()
        threading.Thread(target=self._handle_exec, args=(channel, cmd), daemon=True).start()
        return True

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True

    def _current_commands(self):
        try:
            return self._command_provider()
        except Exception as e:
            log_queue.put(f"[error] Cannot load commands: {e}")
            return self._commands

    def _lookup(self, name):
        for c in self._current_commands():
            if c["name"] == name:
                return c
        return None

    def _handle_shell(self, channel):
        try:
            channel.send(b"SmartKit Storage Simulator\r\nType 'help' for available commands.\r\n\r\nsmartkit:/>")
            buf = b""
            while not channel.closed:
                try:
                    data = channel.recv(1024)
                except Exception:
                    continue
                if not data:
                    continue
                for b in data:
                    if b in (0x7f, 0x08):
                        if buf: buf = buf[:-1]; channel.send(b"\b \b")
                        continue
                    channel.send(bytes([b]))
                    if b in (0x0d, 0x0a):
                        if b == 0x0d: channel.send(b"\n")
                        cmd = buf.decode("utf-8", errors="replace").strip()
                        buf = b""
                        log_queue.put(f"shell: {cmd}" if cmd else "shell: <empty>")
                        if cmd in ("exit", "quit"):
                            channel.send(b"Goodbye.\r\n"); channel.close(); return
                        if cmd == "help":
                            channel.send(b"Available commands:\r\n")
                            for c in self._current_commands():
                                channel.send(f"  {c['name']:<28s} - {c.get('description','')}\r\n".encode())
                            channel.send(b"  exit / quit           - Close this session\r\n")
                            channel.send(b"  help                  - Show this help\r\n")
                        else:
                            entry = self._lookup(cmd)
                            if entry:
                                channel.send(format_command_output(substitute_variables(entry["output"])).encode())
                            elif cmd:
                                channel.send(f"Unknown command: {cmd}\r\n".encode())
                                channel.send(b"Type 'help' for available commands.\r\n")
                        channel.send(b"smartkit:/>")
                        continue
                    buf += bytes([b])
        except (EOFError, OSError):
            pass
        finally:
            channel.close()

    def _handle_exec(self, channel, command):
        try:
            log_queue.put(f"exec: {command}")
            entry = self._lookup(command)
            if entry:
                channel.send(format_command_output(substitute_variables(entry["output"])).encode())
            else:
                channel.send(f"Unknown command: {command}\r\n".encode())
            channel.send_exit_status(0)
        except:
            channel.send_exit_status(1)
        finally:
            channel.close()

def run_server(bind_address, port, username, password, commands, server_stop_event=None):
    bind_address = (bind_address or "127.0.0.1").strip() or "127.0.0.1"
    stop_signal = server_stop_event or stop_event
    if not os.path.exists(HOST_KEY_PATH):
        paramiko.RSAKey.generate(2048).write_private_key_file(HOST_KEY_PATH)
    host_key = paramiko.RSAKey(filename=HOST_KEY_PATH)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(1.0)
    try:
        sock.bind((bind_address, port))
    except OSError as e:
        log_queue.put(f"[error] Cannot bind {bind_address}:{port}: {e}")
        return
    sock.listen(5)
    log_queue.put(f"Server listening on {bind_address}:{port}")
    while not stop_signal.is_set():
        try:
            client, addr = sock.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        log_queue.put(f"Connection from {addr[0]}:{addr[1]}")
        transport = paramiko.Transport(client)
        transport.add_server_key(host_key)
        server = SimulatorServer(username, password, commands,
                                 lambda: active_config().get("commands", []), active_config)
        try:
            transport.start_server(server=server)
        except paramiko.SSHException as e:
            log_queue.put(f"[error] SSH negotiation: {e}")
            continue
        def wait_transport(t):
            channels = []
            try:
                while t.is_active():
                    chan = t.accept(1)
                    if chan is not None:
                        channels.append(chan)
                    channels[:] = [chan for chan in channels if not chan.closed]
            except (EOFError, OSError): pass
        threading.Thread(target=wait_transport, args=(transport,), daemon=True).start()
    sock.close()
    log_queue.put("Server stopped")

def stop_server_thread(timeout=3.0):
    global server_thread
    stop_event.set()
    if server_thread and server_thread.is_alive():
        server_thread.join(timeout)
        if server_thread.is_alive():
            log_queue.put("[error] Previous server did not stop in time")
            return False
    server_thread = None
    return True

REST_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD")
REST_PATH_PARAM = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

def match_rest_route(method, path, routes):
    candidates = [route for route in routes if route.get("method", "GET").upper() == method]
    for route in candidates:
        if route.get("uri") == path:
            return route, {}
    for route in candidates:
        template = route.get("uri", "")
        names = []
        cursor = 0
        pattern = "^"
        for match in REST_PATH_PARAM.finditer(template):
            name = match.group(1)
            if name in names:
                pattern = ""
                break
            names.append(name)
            pattern += re.escape(template[cursor:match.start()]) + f"(?P<{name}>[^/]+)"
            cursor = match.end()
        if not names or not pattern:
            continue
        pattern += re.escape(template[cursor:]) + "$"
        matched = re.match(pattern, path)
        if matched:
            return route, {name: urllib.parse.unquote(value) for name, value in matched.groupdict().items()}
    return None, {}

def substitute_path_parameters(text, parameters):
    for name, value in parameters.items():
        text = text.replace("{" + name + "}", value)
    return text

def create_rest_app():
    rest_app = Flask("smartkit_rest_simulator")

    @rest_app.route("/", defaults={"uri": ""}, methods=REST_METHODS)
    @rest_app.route("/<path:uri>", methods=REST_METHODS)
    def simulate_rest(uri):
        path = "/" + uri
        method = request.method.upper()
        config = active_config()
        route, path_parameters = match_rest_route(method, path, config.get("rest_routes", []))
        if route is None:
            log_queue.put(f"REST {method} {path} -> 404")
            return Response("No simulated route configured\n", status=404,
                            content_type="text/plain; charset=utf-8")
        status = int(route.get("status_code", 200))
        response = Response(substitute_path_parameters(route.get("response_body", ""), path_parameters), status=status)
        for name, value in route.get("response_headers", {}).items():
            response.headers[str(name)] = substitute_path_parameters(str(value), path_parameters)
        log_queue.put(f"REST {method} {path} -> {status}")
        return response

    return rest_app

def stop_rest_server_thread(timeout=3.0):
    global rest_server, rest_thread
    if rest_server is not None:
        rest_server.shutdown()
    if rest_thread and rest_thread.is_alive():
        rest_thread.join(timeout)
        if rest_thread.is_alive():
            log_queue.put("[error] Previous REST server did not stop in time")
            return False
    rest_server = None
    rest_thread = None
    return True

@app.route("/")
def index():
    with open(resource_path("prototype_dataset_ui_a_full.html"), encoding="utf-8") as stream:
        return stream.read()

@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(load_config())

@app.route("/api/config", methods=["POST"])
def api_save_config():
    save_config(request.get_json())
    return jsonify({"status": "ok"})

@app.route("/api/dataset-directory/switch", methods=["POST"])
def api_switch_dataset_directory():
    try:
        path = (request.get_json() or {}).get("path", "")
        return jsonify(dataset_workspace().switch_directory(path))
    except WorkspaceError as error:
        return jsonify({"status": "error", "message": str(error)}), 400

@app.route("/api/dataset-directory", methods=["GET"])
def api_get_dataset_directory():
    workspace = dataset_workspace()
    return jsonify({"path": str(workspace.dataset_dir), **workspace.scan_summary()})

@app.route("/api/dataset-directory/validate", methods=["POST"])
def api_validate_dataset_directory():
    try:
        path = (request.get_json() or {}).get("path", "")
        return jsonify(dataset_workspace().validate_directory(path))
    except (OSError, WorkspaceError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400

@app.route("/api/dataset-directory/rescan", methods=["POST"])
def api_rescan_dataset_directory():
    return jsonify({"status": "ok", **dataset_workspace().scan_summary()})

@app.route("/api/datasets", methods=["GET"])
def api_list_datasets():
    try:
        return jsonify(dataset_workspace().list_datasets(
            request.args.get("page", 1), request.args.get("page_size", 20),
            request.args.get("keyword", "")))
    except (WorkspaceError, ValueError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400

@app.route("/api/datasets", methods=["POST"])
def api_create_dataset():
    try:
        return jsonify(dataset_workspace().create_dataset(request.get_json() or {})), 201
    except ConflictError as error:
        return jsonify({"status": "error", "message": str(error)}), 409
    except WorkspaceError as error:
        return jsonify({"status": "error", "message": str(error)}), 400

@app.route("/api/datasets/<dataset_id>", methods=["GET"])
def api_get_dataset(dataset_id):
    try:
        return jsonify(dataset_workspace().get_dataset(dataset_id))
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "数据集不存在"}), 404
    except WorkspaceError as error:
        return jsonify({"status": "error", "message": str(error)}), 400

@app.route("/api/datasets/<dataset_id>", methods=["PUT"])
def api_update_dataset(dataset_id):
    try:
        return jsonify(dataset_workspace().update_dataset(dataset_id, request.get_json() or {}))
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "数据集不存在"}), 404
    except ConflictError as error:
        return jsonify({"status": "error", "message": str(error)}), 409
    except WorkspaceError as error:
        return jsonify({"status": "error", "message": str(error)}), 400

@app.route("/api/datasets/<dataset_id>/copy", methods=["POST"])
def api_copy_dataset(dataset_id):
    payload = request.get_json() or {}
    try:
        return jsonify(dataset_workspace().copy_dataset(
            dataset_id, payload.get("id", ""), payload.get("name", ""))), 201
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "数据集不存在"}), 404
    except ConflictError as error:
        return jsonify({"status": "error", "message": str(error)}), 409
    except WorkspaceError as error:
        return jsonify({"status": "error", "message": str(error)}), 400

@app.route("/api/datasets/import", methods=["POST"])
def api_import_dataset():
    try:
        payload = request.get_json() or {}
        return jsonify(dataset_workspace().import_dataset(payload.get("dataset"))), 201
    except ConflictError as error:
        return jsonify({"status": "error", "message": str(error)}), 409
    except WorkspaceError as error:
        return jsonify({"status": "error", "message": str(error)}), 400

@app.route("/api/datasets/<dataset_id>/export", methods=["GET"])
def api_export_dataset(dataset_id):
    try:
        workspace = dataset_workspace()
        workspace.get_dataset(dataset_id)
        return send_file(workspace.dataset_dir / f"{dataset_id}.json", as_attachment=True,
                         download_name=f"{dataset_id}.json", mimetype="application/json")
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "数据集不存在"}), 404
    except WorkspaceError as error:
        return jsonify({"status": "error", "message": str(error)}), 400

@app.route("/api/cases/sync", methods=["POST"])
def api_sync_cases():
    try:
        return jsonify(dataset_workspace().sync_cases((request.get_json() or {}).get("cases", [])))
    except WorkspaceError as error:
        return jsonify({"status": "error", "message": str(error)}), 400

@app.route("/api/cases", methods=["GET"])
def api_list_cases():
    try:
        return jsonify(dataset_workspace().list_cases(
            request.args.get("page", 1), request.args.get("page_size", 20),
            request.args.get("keyword", ""), request.args.get("module", ""),
            request.args.get("binding_status", "")))
    except (WorkspaceError, ValueError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400

@app.route("/api/bindings", methods=["GET"])
def api_list_bindings():
    try:
        return jsonify(dataset_workspace().list_bindings(
            request.args.get("page", 1), request.args.get("page_size", 20),
            request.args.get("dataset_id", ""), request.args.get("keyword", "")))
    except (WorkspaceError, ValueError) as error:
        return jsonify({"status": "error", "message": str(error)}), 400

@app.route("/api/bindings/<path:case_id>", methods=["PUT"])
def api_bind_case(case_id):
    try:
        return jsonify(dataset_workspace().bind_case(case_id, (request.get_json() or {}).get("dataset_id", "")))
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "数据集不存在"}), 404
    except WorkspaceError as error:
        return jsonify({"status": "error", "message": str(error)}), 400

@app.route("/api/bindings/<path:case_id>", methods=["DELETE"])
def api_unbind_case(case_id):
    if not dataset_workspace().unbind_case(case_id):
        return jsonify({"status": "error", "message": "绑定不存在"}), 404
    return jsonify({"status": "ok"})

@app.route("/api/bindings/import", methods=["POST"])
def api_import_bindings():
    try:
        return jsonify(dataset_workspace().import_bindings(
            (request.get_json() or {}).get("bindings", [])))
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "绑定引用的数据集不存在"}), 404
    except WorkspaceError as error:
        return jsonify({"status": "error", "message": str(error)}), 400

@app.route("/api/runtime/health", methods=["GET"])
def api_runtime_health():
    return jsonify({"status": "ready", "runtime": _runtime_result()})

@app.route("/api/runtime/status", methods=["GET"])
def api_runtime_status():
    return jsonify(_runtime_result())

@app.route("/api/runtime/activate-case", methods=["POST"])
def api_runtime_activate_case():
    global runtime_snapshot
    payload = request.get_json() or {}
    case_id = str(payload.get("case_id", "")).strip()
    execution_id = str(payload.get("execution_id", "")).strip()
    if not case_id or not execution_id:
        return jsonify({"status": "error", "message": "case_id 和 execution_id 不能为空"}), 400
    with runtime_lock:
        if runtime_snapshot:
            if runtime_snapshot["execution_id"] == execution_id and runtime_snapshot["case_id"] == case_id:
                return jsonify({key: value for key, value in runtime_snapshot.items() if key != "snapshot"})
            return jsonify({"status": "error", "message": "模拟器实例正被其他执行占用",
                            "active_execution_id": runtime_snapshot["execution_id"]}), 409
        try:
            dataset_id, dataset = dataset_workspace().resolve_case(case_id)
        except FileNotFoundError:
            return jsonify({"status": "error", "message": "绑定的数据集不存在"}), 404
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 404
        canonical = json.dumps(dataset, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        server = {**DEFAULT_SERVER, **dataset.get("server", {})}
        rest = {**DEFAULT_REST_SERVER, **dataset.get("rest_server", {})}
        runtime_snapshot = {
            "status": "active", "case_id": case_id, "execution_id": execution_id,
            "dataset_id": dataset_id, "dataset_file": f"{dataset_id}.json",
            "dataset_revision": dataset["revision"],
            "checksum": "sha256:" + hashlib.sha256(canonical).hexdigest(),
            "activated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "ssh_endpoint": f"{server['bind_address']}:{server['port']}",
            "rest_endpoint": f"https://{rest['bind_address']}:{rest['port']}",
            "snapshot": copy.deepcopy(dataset),
        }
        result = {key: value for key, value in runtime_snapshot.items() if key != "snapshot"}
    runtime_path = os.path.join(DATA_DIR, "runtime", "active.json")
    os.makedirs(os.path.dirname(runtime_path), exist_ok=True)
    with open(runtime_path, "w", encoding="utf-8") as stream:
        json.dump(runtime_snapshot, stream, ensure_ascii=False, indent=2)
    return jsonify(result)

@app.route("/api/runtime/release", methods=["POST"])
def api_runtime_release():
    global runtime_snapshot
    execution_id = str((request.get_json() or {}).get("execution_id", "")).strip()
    with runtime_lock:
        if not runtime_snapshot:
            return jsonify({"status": "idle"})
        if execution_id != runtime_snapshot["execution_id"]:
            return jsonify({"status": "error", "message": "execution_id 不是当前租约持有者"}), 409
        runtime_snapshot = None
    runtime_path = os.path.join(DATA_DIR, "runtime", "active.json")
    if os.path.exists(runtime_path):
        os.unlink(runtime_path)
    return jsonify({"status": "released", "execution_id": execution_id})

@app.route("/api/runtime/activate-dataset", methods=["POST"])
def api_runtime_activate_dataset():
    """Manually activate a dataset from the workbench without creating a case binding."""
    global runtime_snapshot
    payload = request.get_json() or {}
    dataset_id = str(payload.get("dataset_id", "")).strip()
    execution_id = str(payload.get("execution_id", "")).strip()
    if not dataset_id or not execution_id:
        return jsonify({"status": "error", "message": "dataset_id 和 execution_id 不能为空"}), 400
    with runtime_lock:
        if runtime_snapshot:
            return jsonify({"status": "error", "message": "模拟器实例正被其他执行占用",
                            "active_execution_id": runtime_snapshot["execution_id"]}), 409
        try:
            dataset = dataset_workspace().get_dataset(dataset_id)
        except FileNotFoundError:
            return jsonify({"status": "error", "message": "数据集不存在"}), 404
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400
        canonical = json.dumps(dataset, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")
        server = {**DEFAULT_SERVER, **dataset.get("server", {})}
        rest = {**DEFAULT_REST_SERVER, **dataset.get("rest_server", {})}
        runtime_snapshot = {
            "status": "active", "case_id": "manual", "execution_id": execution_id,
            "dataset_id": dataset_id, "dataset_file": f"{dataset_id}.json",
            "dataset_revision": dataset["revision"],
            "checksum": "sha256:" + hashlib.sha256(canonical).hexdigest(),
            "activated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "ssh_endpoint": f"{server['bind_address']}:{server['port']}",
            "rest_endpoint": f"https://{rest['bind_address']}:{rest['port']}",
            "snapshot": copy.deepcopy(dataset),
        }
        result = {key: value for key, value in runtime_snapshot.items() if key != "snapshot"}
    return jsonify(result)

@app.route("/api/ssh/import-log/preview", methods=["POST"])
def api_preview_ssh_log_import():
    payload = request.get_json() or {}
    log_text = str(payload.get("log_text", ""))
    if not log_text.strip():
        return jsonify({"status": "error", "message": "Log text is required."}), 400
    parsed_commands = parse_ssh_commands_from_log(log_text)
    dataset_id = str(payload.get("dataset_id", "")).strip()
    try:
        source = dataset_workspace().get_dataset(dataset_id) if dataset_id else load_config()
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "数据集不存在"}), 404
    except WorkspaceError as error:
        return jsonify({"status": "error", "message": str(error)}), 400
    existing = {str(command.get("name", "")) for command in source.get("commands", [])}
    results = []
    for command in parsed_commands:
        name = command["name"]
        if command["output"] is None:
            results.append({"status": "missing_response", "message": "No matching response was found.",
                            "command": command})
        elif name in existing:
            results.append({"status": "duplicate", "message": "The same command already exists.",
                            "command": command})
        else:
            results.append({"status": "ready", "message": "Ready to import.",
                            "command": command})
            existing.add(name)
    summary = {
        "total": len(results),
        "importable": sum(result["status"] == "ready" for result in results),
        "duplicate": sum(result["status"] == "duplicate" for result in results),
        "incomplete": sum(result["status"] == "missing_response" for result in results),
    }
    return jsonify({"status": "ok", "summary": summary, "commands": results})

@app.route("/api/rest/import-log/preview", methods=["POST"])
def api_preview_rest_log_import():
    payload = request.get_json() or {}
    log_text = str(payload.get("log_text", ""))
    if not log_text.strip():
        return jsonify({"status": "error", "message": "Log text is required."}), 400
    parsed_routes = parse_rest_routes_from_log(log_text)
    dataset_id = str(payload.get("dataset_id", "")).strip()
    try:
        source = dataset_workspace().get_dataset(dataset_id) if dataset_id else load_config()
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "数据集不存在"}), 404
    except WorkspaceError as error:
        return jsonify({"status": "error", "message": str(error)}), 400
    existing = {(str(route.get("method", "GET")).upper(), str(route.get("uri", "")))
                for route in source.get("rest_routes", [])}
    results = []
    for route in parsed_routes:
        key = (route["method"], route["uri"])
        if route["response_body"] is None:
            results.append({"status": "missing_response", "message": "No matching response was found.",
                            "route": route})
        elif key in existing:
            results.append({"status": "duplicate", "message": "The same method and URI already exist.",
                            "route": route})
        else:
            results.append({"status": "ready", "message": "Ready to import.", "route": route})
            existing.add(key)
    summary = {
        "total": len(results),
        "importable": sum(result["status"] == "ready" for result in results),
        "duplicate": sum(result["status"] == "duplicate" for result in results),
        "incomplete": sum(result["status"] == "missing_response" for result in results),
    }
    return jsonify({"status": "ok", "summary": summary, "routes": results})

@app.route("/api/rest/start", methods=["POST"])
def api_start_rest_server():
    global rest_server, rest_thread
    config = load_config()
    data = request.get_json() or {}
    bind_address = (data.get("bind_address") or config["rest_server"]["bind_address"]).strip()
    port = int(data.get("port", config["rest_server"]["port"]))
    if not 1 <= port <= 65535:
        return jsonify({"status": "error", "message": "port must be between 1 and 65535"}), 400
    config["rest_server"] = {"bind_address": bind_address, "port": port}
    save_config(config)
    with rest_lock:
        if not stop_rest_server_thread():
            return jsonify({"status": "error", "message": "previous REST server did not stop"}), 409
        try:
            rest_server = make_server(bind_address, port, create_rest_app(), threaded=True,
                                      ssl_context=create_rest_tls_context())
        except (OSError, ssl.SSLError) as e:
            log_queue.put(f"[error] Cannot bind REST {bind_address}:{port}: {e}")
            return jsonify({"status": "error", "message": str(e)}), 409
        rest_thread = threading.Thread(target=rest_server.serve_forever, daemon=True)
        rest_thread.start()
    log_queue.put(f"REST TLS 1.2/1.3 server listening on {bind_address}:{port}")
    access_addresses = local_ipv4_addresses() if bind_address == "0.0.0.0" else [bind_address]
    return jsonify({"status": "running", "bind_address": bind_address, "port": port,
                    "tls_versions": ["TLSv1.2", "TLSv1.3"],
                    "access_urls": [f"https://{address}:{port}" for address in access_addresses]})

@app.route("/api/rest/stop", methods=["POST"])
def api_stop_rest_server():
    with rest_lock:
        stop_rest_server_thread()
    log_queue.put("REST server stopped")
    return jsonify({"status": "stopped"})

@app.route("/api/rest/test", methods=["POST"])
def api_test_rest_request():
    data = request.get_json() or {}
    method = str(data.get("method", "GET")).upper()
    url = str(data.get("url", "")).strip()
    headers = data.get("headers") or {}
    body = data.get("body", "")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return jsonify({"status": "error", "message": "URL must use http:// or https://"}), 400
    if not isinstance(headers, dict):
        return jsonify({"status": "error", "message": "headers must be an object"}), 400
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    started = time.perf_counter()
    connection = None
    try:
        if parsed.scheme == "https":
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.maximum_version = ssl.TLSVersion.TLSv1_3
            connection = http.client.HTTPSConnection(parsed.hostname, port, timeout=10, context=context)
        else:
            connection = http.client.HTTPConnection(parsed.hostname, port, timeout=10)
        payload = body.encode("utf-8") if isinstance(body, str) else body
        connection.request(method, target, body=payload, headers={str(k): str(v) for k, v in headers.items()})
        tls_version = connection.sock.version() if parsed.scheme == "https" and connection.sock else None
        response = connection.getresponse()
        response_body = response.read().decode("utf-8", errors="replace")
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        log_queue.put(f"REST test {method} {url} -> {response.status} ({elapsed_ms} ms)")
        return jsonify({"status": "ok", "status_code": response.status, "reason": response.reason,
                        "elapsed_ms": elapsed_ms, "tls_version": tls_version,
                        "response_headers": response.getheaders(), "response_body": response_body,
                        "request_url": url})
    except (OSError, ssl.SSLError, http.client.HTTPException, ValueError) as e:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        log_queue.put(f"[error] REST test {method} {url}: {e}")
        return jsonify({"status": "error", "message": str(e), "elapsed_ms": elapsed_ms}), 502
    finally:
        if connection is not None:
            connection.close()

@app.route("/api/server/start", methods=["POST"])
def api_start_server():
    global stop_event, server_thread
    config = load_config()
    data = request.get_json() or {}
    bind_address = data.get("bind_address", config["server"].get("bind_address", "127.0.0.1"))
    bind_address = (bind_address or "127.0.0.1").strip() or "127.0.0.1"
    port = data.get("port", config["server"]["port"])
    username = data.get("username", config["server"]["username"])
    password = data.get("password", config["server"]["password"])
    config["server"] = {
        "bind_address": bind_address,
        "port": port,
        "username": username,
        "password": password,
    }
    save_config(config)
    with server_lock:
        if not stop_server_thread():
            return jsonify({"status": "error", "message": "previous server did not stop"}), 409
        stop_event = threading.Event()
        server_thread = threading.Thread(
            target=run_server,
            args=(bind_address, port, username, password, list(config["commands"]), stop_event),
            daemon=True,
        )
        server_thread.start()
    return jsonify({"status": "running", "bind_address": bind_address, "port": port})

@app.route("/api/server/stop", methods=["POST"])
def api_stop_server():
    with server_lock:
        stop_server_thread()
    return jsonify({"status": "stopped"})

@app.route("/api/logs", methods=["GET"])
def api_get_logs():
    logs = []
    while True:
        try:
            logs.append(log_queue.get_nowait())
        except queue.Empty:
            break
    return jsonify(logs)

@app.route("/api/services/status", methods=["GET"])
def api_services_status():
    return jsonify({
        "ssh": bool(server_thread and server_thread.is_alive() and not stop_event.is_set()),
        "rest": bool(rest_thread and rest_thread.is_alive() and rest_server is not None),
    })

def parse_args(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="SmartKit Storage Simulator")
    parser.add_argument("--headless", action="store_true",
                        help="Run without browser; print SMARTKIT_READY_PORT=<port>")
    parser.add_argument("--data-dir", default=None,
                        help="Directory for config.json and host_key")
    return parser.parse_args(argv)

def run_headless():
    server = make_server("127.0.0.1", 0, app, threaded=True)
    print(f"SMARTKIT_READY_PORT={server.server_port}", flush=True)
    server.serve_forever()

if __name__ == "__main__":
    args = parse_args()
    if args.data_dir:
        set_data_dir(args.data_dir)
    if args.headless:
        run_headless()
    else:
        port = 5800
        for p in range(5800, 5900):
            try:
                s = socket.socket()
                s.bind(("127.0.0.1", p))
                s.close()
                port = p
                break
            except OSError:
                continue
        url = f"http://127.0.0.1:{port}"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        print(f"GUI running at {url}")
        app.run(host="127.0.0.1", port=port, debug=False)
