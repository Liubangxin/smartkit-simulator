"""GET / - serve the single-file dataset workbench UI."""

from flask import Blueprint

from ..paths import resource_path


def register(state):
    bp = Blueprint("index", __name__)

    @bp.route("/")
    def index():
        with open(resource_path("workbench.html"), encoding="utf-8") as stream:
            return stream.read()

    return bp
