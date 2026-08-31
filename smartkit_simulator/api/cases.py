"""Case catalog and case-binding API."""

from flask import Blueprint, jsonify, request

from ..errors import WorkspaceError


def register(state):
    bp = Blueprint("cases", __name__)

    @bp.route("/api/cases/sync", methods=["POST"])
    def sync_cases():
        try:
            return jsonify(state.dataset_workspace().sync_cases(
                (request.get_json() or {}).get("cases", [])))
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    @bp.route("/api/cases", methods=["GET"])
    def list_cases():
        try:
            return jsonify(state.dataset_workspace().list_cases(
                request.args.get("page", 1), request.args.get("page_size", 20),
                request.args.get("keyword", ""), request.args.get("module", ""),
                request.args.get("binding_status", "")))
        except (WorkspaceError, ValueError) as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    @bp.route("/api/bindings", methods=["GET"])
    def list_bindings():
        try:
            return jsonify(state.dataset_workspace().list_bindings(
                request.args.get("page", 1), request.args.get("page_size", 20),
                request.args.get("dataset_id", ""), request.args.get("keyword", "")))
        except (WorkspaceError, ValueError) as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    @bp.route("/api/bindings/<path:case_id>", methods=["PUT"])
    def bind_case(case_id):
        try:
            return jsonify(state.dataset_workspace().bind_case(
                case_id, (request.get_json() or {}).get("dataset_id", "")))
        except FileNotFoundError:
            return jsonify({"status": "error", "message": "数据集不存在"}), 404
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    @bp.route("/api/bindings/<path:case_id>", methods=["DELETE"])
    def unbind_case(case_id):
        if not state.dataset_workspace().unbind_case(case_id):
            return jsonify({"status": "error", "message": "绑定不存在"}), 404
        return jsonify({"status": "ok"})

    @bp.route("/api/bindings/import", methods=["POST"])
    def import_bindings():
        try:
            return jsonify(state.dataset_workspace().import_bindings(
                (request.get_json() or {}).get("bindings", [])))
        except FileNotFoundError:
            return jsonify({"status": "error", "message": "绑定引用的数据集不存在"}), 404
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    return bp
