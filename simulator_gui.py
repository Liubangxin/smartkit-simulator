#!/usr/bin/env python3
"""SmartKit Storage Simulator - Web GUI (Flask)

Backward-compatible entry point and re-export shim for the refactored
``smartkit_simulator`` package.

Electron, PyInstaller, ``start_gui.ps1``, the docs and the existing test
suite all import or launch ``simulator_gui`` and keep working unchanged.
Functions that used to read module globals are wrapped so they keep their
original no-argument signatures and read the current application state.
Module-level attributes that can be replaced at runtime (``stop_event``,
``server_thread``, ``DATA_DIR``, ...) are exposed through ``__getattr__`` so
they always reflect the current application state.
"""

from smartkit_simulator.application import application as _application
from smartkit_simulator.application import app
from smartkit_simulator.import_logs.common import log_thread_id
from smartkit_simulator.import_logs.rest_parser import parse_rest_routes_from_log
from smartkit_simulator.import_logs.ssh_parser import (clean_ssh_received_output,
                                                       parse_ssh_commands_from_log)
from smartkit_simulator.legacy import normalize_groups
from smartkit_simulator.paths import BASE_DIR, resource_path
from smartkit_simulator.rest.matching import (REST_METHODS, REST_PATH_PARAM,
                                              match_rest_route, substitute_path_parameters)
from smartkit_simulator.rest.server import stop_rest_server_thread as _stop_rest_server_thread
from smartkit_simulator.settings import (DEFAULT_APP_SETTINGS, DEFAULT_REST_SERVER,
                                         DEFAULT_SERVER, local_ipv4_addresses)
from smartkit_simulator.ssh.rendering import format_command_output, substitute_variables
from smartkit_simulator.ssh.server import SimulatorServer, run_server
from smartkit_simulator.ssh.server import stop_server_thread as _stop_server_thread
from smartkit_simulator.workspace.store import DatasetWorkspace

#: Stable objects that are never replaced at runtime.
log_queue = _application.log_queue
server_lock = _application.server_lock
rest_lock = _application.rest_lock

#: Names that are replaced at runtime (set_data_dir / server lifecycle) and
#: therefore resolved live through the application state.
_DYNAMIC_ATTRIBUTES = frozenset((
    "DATA_DIR", "CONFIG_PATH", "HOST_KEY_PATH", "REST_CERT_PATH", "REST_KEY_PATH",
    "stop_event", "server_thread", "rest_server", "rest_thread",
    "runtime_snapshot", "runtime_lock",
))


def __getattr__(name):
    if name == "runtime_snapshot":
        return _application.runtime._snapshot
    if name == "runtime_lock":
        return _application.runtime._lock
    if name in _DYNAMIC_ATTRIBUTES:
        return getattr(_application, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def set_data_dir(path):
    _application.set_data_dir(path)


def dataset_workspace():
    return _application.dataset_workspace()


def active_config():
    return _application.active_config()


def reset_runtime_state():
    _application.reset_runtime_state()


def load_config():
    return _application.load_config()


def save_config(config):
    return _application.save_config(config)


def load_app_settings():
    return _application.load_app_settings()


def save_app_settings(payload):
    return _application.save_app_settings(payload)


def stop_server_thread(timeout=3.0):
    return _stop_server_thread(_application, timeout)


def stop_rest_server_thread(timeout=3.0):
    return _stop_rest_server_thread(_application, timeout)


def create_rest_app():
    from smartkit_simulator.rest.server import create_rest_app as _create_rest_app
    return _create_rest_app(_application)


def ensure_rest_certificate():
    from smartkit_simulator.security.tls import ensure_rest_certificate as _ensure
    return _ensure(_application)


def create_rest_tls_context():
    from smartkit_simulator.security.tls import create_rest_tls_context as _create
    return _create(_application)


def parse_args(argv=None):
    from smartkit_simulator.__main__ import parse_args as _parse_args
    return _parse_args(argv)


def run_headless(management_port=None):
    from smartkit_simulator.__main__ import run_headless as _run_headless
    return _run_headless(management_port)


def main():
    from smartkit_simulator.__main__ import main as _main
    return _main()


if __name__ == "__main__":
    main()
