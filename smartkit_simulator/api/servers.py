"""Protocol server control API: SSH start/stop, REST start/stop/test, status."""

import http.client
import ssl
import threading
import time
import urllib.parse

from flask import Blueprint, jsonify, request

from ..rest.server import start_rest_server, stop_rest_server_thread
from ..settings import local_ipv4_addresses
from ..ssh.server import stop_server_thread


def register(state):
    bp = Blueprint("servers", __name__)

    @bp.route("/api/server/start", methods=["POST"])
    def start_server():
        settings = state.load_app_settings()
        ssh_settings = settings["ssh_server"]
        data = request.get_json() or {}
        bind_address = data.get("bind_address", ssh_settings["bind_address"])
        bind_address = (bind_address or "127.0.0.1").strip() or "127.0.0.1"
        port = data.get("port", ssh_settings["port"])
        username = data.get("username", ssh_settings["username"])
        password = data.get("password", ssh_settings["password"])
        state.save_app_settings({"ssh_server": {"bind_address": bind_address, "port": port,
                                                "username": username, "password": password}})
        with state.server_lock:
            if not stop_server_thread(state):
                return jsonify({"status": "error", "message": "previous server did not stop"}), 409
            state.stop_event = threading.Event()
            state.server_thread = threading.Thread(
                target=state.ssh_runner,
                args=(bind_address, port, username, password,
                      list(state.active_config().get("commands", [])), state.stop_event),
                daemon=True,
            )
            state.server_thread.start()
        return jsonify({"status": "running", "bind_address": bind_address, "port": port})

    @bp.route("/api/server/stop", methods=["POST"])
    def stop_server():
        with state.server_lock:
            stop_server_thread(state)
        return jsonify({"status": "stopped"})

    @bp.route("/api/rest/start", methods=["POST"])
    def start_rest():
        settings = state.load_app_settings()
        data = request.get_json() or {}
        bind_address = (data.get("bind_address") or settings["rest_server"]["bind_address"]).strip()
        port = int(data.get("port", settings["rest_server"]["port"]))
        if not 1 <= port <= 65535:
            return jsonify({"status": "error", "message": "port must be between 1 and 65535"}), 400
        state.save_app_settings({"rest_server": {"bind_address": bind_address, "port": port}})
        with state.rest_lock:
            if not stop_rest_server_thread(state):
                return jsonify({"status": "error", "message": "previous REST server did not stop"}), 409
            try:
                result = start_rest_server(state, bind_address, port)
            except (OSError, ssl.SSLError) as error:
                state.log_queue.put(f"[error] Cannot bind REST {bind_address}:{port}: {error}")
                return jsonify({"status": "error", "message": str(error)}), 409
        return jsonify(result)

    @bp.route("/api/rest/stop", methods=["POST"])
    def stop_rest():
        with state.rest_lock:
            stop_rest_server_thread(state)
        state.log_queue.put("REST server stopped")
        return jsonify({"status": "stopped"})

    @bp.route("/api/rest/test", methods=["POST"])
    def test_rest_request():
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
                connection = http.client.HTTPSConnection(parsed.hostname, port, timeout=10,
                                                         context=context)
            else:
                connection = http.client.HTTPConnection(parsed.hostname, port, timeout=10)
            payload = body.encode("utf-8") if isinstance(body, str) else body
            connection.request(method, target, body=payload,
                               headers={str(k): str(v) for k, v in headers.items()})
            tls_version = connection.sock.version() if parsed.scheme == "https" and connection.sock else None
            response = connection.getresponse()
            response_body = response.read().decode("utf-8", errors="replace")
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            state.log_queue.put(f"REST test {method} {url} -> {response.status} ({elapsed_ms} ms)")
            return jsonify({"status": "ok", "status_code": response.status,
                            "reason": response.reason, "elapsed_ms": elapsed_ms,
                            "tls_version": tls_version,
                            "response_headers": response.getheaders(),
                            "response_body": response_body, "request_url": url})
        except (OSError, ssl.SSLError, http.client.HTTPException, ValueError) as error:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            state.log_queue.put(f"[error] REST test {method} {url}: {error}")
            return jsonify({"status": "error", "message": str(error),
                            "elapsed_ms": elapsed_ms}), 502
        finally:
            if connection is not None:
                connection.close()

    @bp.route("/api/services/status", methods=["GET"])
    def services_status():
        return jsonify({
            "ssh": bool(state.server_thread and state.server_thread.is_alive()
                        and not state.stop_event.is_set()),
            "rest": bool(state.rest_thread and state.rest_thread.is_alive()
                         and state.rest_server is not None),
        })

    return bp
