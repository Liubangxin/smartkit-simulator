#!/usr/bin/env python3
"""SmartKit Storage Simulator - Web GUI (Flask)"""

import json, os, queue, socket, ssl, sys, threading, time, datetime, random, string, webbrowser, ipaddress, http.client, urllib.parse, re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

import paramiko
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from flask import Flask, request, jsonify, Response
from werkzeug.serving import make_server

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

class SimulatorServer(paramiko.ServerInterface):
    def __init__(self, username, password, commands, command_provider=None):
        self._username, self._password, self._commands = username, password, commands
        self._command_provider = command_provider or (lambda: self._commands)

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if username == self._username and password == self._password else paramiko.AUTH_FAILED

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
        server = SimulatorServer(username, password, commands, lambda: load_config().get("commands", []))
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
        config = load_config()
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
    return open(resource_path("index.html"), encoding="utf-8").read()

@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(load_config())

@app.route("/api/config", methods=["POST"])
def api_save_config():
    save_config(request.get_json())
    return jsonify({"status": "ok"})

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
