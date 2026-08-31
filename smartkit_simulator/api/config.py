"""Legacy config API: GET/POST /api/config (single-file pre-dataset format)."""

from flask import Blueprint, jsonify, request


def register(state):
    bp = Blueprint("legacy_config", __name__)

    @bp.route("/api/config", methods=["GET"])
    def get_config():
        return jsonify(state.load_config())

    @bp.route("/api/config", methods=["POST"])
    def save_config():
        state.save_config(request.get_json())
        return jsonify({"status": "ok"})

    return bp
