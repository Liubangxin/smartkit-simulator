"""Werkzeug/Flask based REST HTTPS simulator.

The Flask app reads the *active* configuration through ``state.active_config()``
so an activated immutable snapshot is served until it is released, and the
legacy ``config.json`` otherwise.
"""

import ssl
import threading

from flask import Flask, Response, request
from werkzeug.serving import make_server

from ..security.tls import create_rest_tls_context
from ..settings import local_ipv4_addresses
from .matching import REST_METHODS, match_rest_route, substitute_path_parameters


def create_rest_app(state):
    rest_app = Flask("smartkit_rest_simulator")

    @rest_app.route("/", defaults={"uri": ""}, methods=REST_METHODS)
    @rest_app.route("/<path:uri>", methods=REST_METHODS)
    def simulate_rest(uri):
        path = "/" + uri
        method = request.method.upper()
        config = state.active_config()
        route, path_parameters = match_rest_route(method, path, config.get("rest_routes", []))
        if route is None:
            state.log_queue.put(f"REST {method} {path} -> 404")
            return Response("No simulated route configured\n", status=404,
                            content_type="text/plain; charset=utf-8")
        status = int(route.get("status_code", 200))
        response = Response(substitute_path_parameters(route.get("response_body", ""),
                                                       path_parameters),
                            status=status)
        for name, value in route.get("response_headers", {}).items():
            response.headers[str(name)] = substitute_path_parameters(str(value), path_parameters)
        state.log_queue.put(f"REST {method} {path} -> {status}")
        return response

    return rest_app


def stop_rest_server_thread(state=None, timeout=3.0):
    if state is None:
        from ..application import application as default_state
        state = default_state
    if state.rest_server is not None:
        state.rest_server.shutdown()
    if state.rest_thread and state.rest_thread.is_alive():
        state.rest_thread.join(timeout)
        if state.rest_thread.is_alive():
            state.log_queue.put("[error] Previous REST server did not stop in time")
            return False
    state.rest_server = None
    state.rest_thread = None
    return True


def start_rest_server(state, bind_address, port):
    """Bind and start the REST simulator; returns the JSON-able status dict.

    Raises ``OSError`` / ``ssl.SSLError`` on bind or TLS setup failure so the
    caller can map them to a 409 response.
    """
    server = make_server(bind_address, port, create_rest_app(state), threaded=True,
                         ssl_context=create_rest_tls_context(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.rest_server = server
    state.rest_thread = thread
    state.log_queue.put(f"REST TLS 1.2/1.3 server listening on {bind_address}:{port}")
    access_addresses = local_ipv4_addresses() if bind_address == "0.0.0.0" else [bind_address]
    return {"status": "running", "bind_address": bind_address, "port": port,
            "tls_versions": ["TLSv1.2", "TLSv1.3"],
            "access_urls": [f"https://{address}:{port}" for address in access_addresses]}
