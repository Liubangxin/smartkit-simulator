#!/usr/bin/env python3
"""SmartKit Storage Simulator - Web GUI (Flask)"""

import json, os, queue, socket, threading, time, datetime, random, string, webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

import paramiko
from flask import Flask, request, jsonify

def resource_path(relative_path):
    return os.path.join(BASE_DIR, relative_path)

def writable_path(relative_path):
    return os.path.join(BASE_DIR, relative_path)

CONFIG_PATH = writable_path("config.json")
HOST_KEY_PATH = os.path.join(BASE_DIR, "host_key")
app = Flask(__name__)
log_queue = queue.Queue()
stop_event = threading.Event()
server_thread = None
server_lock = threading.Lock()

DEFAULT_SERVER = {
    "bind_address": "127.0.0.1",
    "port": 2222,
    "username": "admin",
    "password": "admin123",
}

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

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
            config["server"] = {**DEFAULT_SERVER, **config.get("server", {})}
            return config
    bundled_config = resource_path("config.json")
    if os.path.exists(bundled_config):
        with open(bundled_config, "r", encoding="utf-8") as f:
            config = json.load(f)
            config["server"] = {**DEFAULT_SERVER, **config.get("server", {})}
            return config
    return {"server": dict(DEFAULT_SERVER), "commands": []}

def save_config(config):
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
            channel.send(b"SmartKit Storage Simulator\r\nType 'help' for available commands.\r\n\r\nsmartkit> ")
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
                        channel.send(b"smartkit> ")
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

if __name__ == "__main__":
    port = 5800
    for p in range(5800, 5900):
        try:
            s = socket.socket()
            s.bind(("127.0.0.1", p))
            s.close()
            port = p
            break
        except:
            continue
    url = f"http://127.0.0.1:{port}"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"GUI running at {url}")
    app.run(host="127.0.0.1", port=port, debug=False)
