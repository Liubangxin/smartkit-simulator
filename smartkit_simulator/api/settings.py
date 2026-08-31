"""Global settings API: GET/PUT /api/settings."""

from flask import Blueprint, jsonify, request

from ..errors import WorkspaceError


def register(state):
    bp = Blueprint("app_settings", __name__)

    @bp.route("/api/settings", methods=["GET"])
    def get_settings():
        try:
            return jsonify(state.load_app_settings())
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    @bp.route("/api/settings", methods=["PUT"])
    def update_settings():
        try:
            return jsonify(state.save_app_settings(request.get_json() or {}))
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    return bp
