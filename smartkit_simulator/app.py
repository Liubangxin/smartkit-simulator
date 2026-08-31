"""Flask app factory for the management API.

Every blueprint receives the same ``state`` (an ``ApplicationState``) and
reads it at request time, so ``set_data_dir`` / runtime changes are visible
without rebuilding the app.  Tests can build a fresh app around their own
state object.
"""

from flask import Flask

from .api import cases, config, datasets, import_logs, index, logs, runtime, servers, settings


def create_app(state):
    app = Flask(__name__)
    for module in (index, datasets, cases, runtime, servers,
                   import_logs, settings, config, logs):
        app.register_blueprint(module.register(state))
    return app
