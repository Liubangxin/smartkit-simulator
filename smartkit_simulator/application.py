"""Process-wide application state.

A single ``ApplicationState`` instance wires the package together and replaces
the old module-level globals of ``simulator_gui.py``:

* data-dir dependent paths (settings.json, host_key, TLS certs)
* the runtime log queue and protocol server thread handles
* the runtime snapshot/lease state
* settings helpers

The root ``simulator_gui.py`` shim re-exports these objects so Electron,
PyInstaller, docs and the existing test suite keep working unchanged.
"""

import os
import queue
import threading

from . import paths
from . import settings as settings_mod
from .app import create_app
from .rest.server import stop_rest_server_thread  # noqa: F401 (re-exported)
from .runtime.state import RuntimeState
from .ssh.server import run_server
from .workspace.store import DatasetWorkspace


class ApplicationState:
    def __init__(self):
        self.data_dir = paths.BASE_DIR
        self.config_path = os.path.join(self.data_dir, "config.json")
        self.host_key_path = os.path.join(self.data_dir, "host_key")
        self.rest_cert_path = os.path.join(self.data_dir, "rest_cert.pem")
        self.rest_key_path = os.path.join(self.data_dir, "rest_key.pem")

        self.log_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.server_thread = None
        self.server_lock = threading.Lock()
        self.rest_server = None
        self.rest_thread = None
        self.rest_lock = threading.Lock()
        self.runtime = RuntimeState(self.data_dir)
        #: SSH runner hook; API route / server/start and tests may override it.
        self.ssh_runner = run_server

    def set_data_dir(self, path):
        self.data_dir = os.path.abspath(path)
        os.makedirs(self.data_dir, exist_ok=True)
        self.config_path = os.path.join(self.data_dir, "config.json")
        self.host_key_path = os.path.join(self.data_dir, "host_key")
        self.rest_cert_path = os.path.join(self.data_dir, "rest_cert.pem")
        self.rest_key_path = os.path.join(self.data_dir, "rest_key.pem")
        self.runtime.data_dir = self.data_dir

    def dataset_workspace(self):
        workspace = DatasetWorkspace(self.data_dir)
        workspace.migrate_legacy(self.config_path)
        return workspace

    def reset_runtime_state(self):
        self.runtime.reset()
        self.stop_event.set()

    def active_config(self):
        return self.runtime.active_config()

    def load_app_settings(self):
        return settings_mod.load_app_settings(self)

    def save_app_settings(self, payload):
        return settings_mod.save_app_settings(self, payload)


application = ApplicationState()
app = create_app(application)
