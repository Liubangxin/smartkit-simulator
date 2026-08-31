"""Dataset directory and dataset file API (CRUD, import/export, scan)."""

from flask import Blueprint, jsonify, request, send_file

from ..errors import ConflictError, WorkspaceError


def register(state):
    bp = Blueprint("datasets", __name__)

    @bp.route("/api/dataset-directory/switch", methods=["POST"])
    def switch_dataset_directory():
        try:
            path = (request.get_json() or {}).get("path", "")
            return jsonify(state.dataset_workspace().switch_directory(path))
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    @bp.route("/api/dataset-directory", methods=["GET"])
    def get_dataset_directory():
        workspace = state.dataset_workspace()
        return jsonify({"path": str(workspace.dataset_dir), **workspace.scan_summary()})

    @bp.route("/api/dataset-directory/validate", methods=["POST"])
    def validate_dataset_directory():
        try:
            path = (request.get_json() or {}).get("path", "")
            return jsonify(state.dataset_workspace().validate_directory(path))
        except (OSError, WorkspaceError) as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    @bp.route("/api/dataset-directory/rescan", methods=["POST"])
    def rescan_dataset_directory():
        return jsonify({"status": "ok", **state.dataset_workspace().scan_summary()})

    @bp.route("/api/datasets", methods=["GET"])
    def list_datasets():
        try:
            return jsonify(state.dataset_workspace().list_datasets(
                request.args.get("page", 1), request.args.get("page_size", 20),
                request.args.get("keyword", "")))
        except (WorkspaceError, ValueError) as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    @bp.route("/api/datasets", methods=["POST"])
    def create_dataset():
        try:
            return jsonify(state.dataset_workspace().create_dataset(request.get_json() or {})), 201
        except ConflictError as error:
            return jsonify({"status": "error", "message": str(error)}), 409
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    @bp.route("/api/datasets/<dataset_id>", methods=["GET"])
    def get_dataset(dataset_id):
        try:
            return jsonify(state.dataset_workspace().get_dataset(dataset_id))
        except FileNotFoundError:
            return jsonify({"status": "error", "message": "数据集不存在"}), 404
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    @bp.route("/api/datasets/<dataset_id>", methods=["PUT"])
    def update_dataset(dataset_id):
        try:
            return jsonify(state.dataset_workspace().update_dataset(
                dataset_id, request.get_json() or {}))
        except FileNotFoundError:
            return jsonify({"status": "error", "message": "数据集不存在"}), 404
        except ConflictError as error:
            return jsonify({"status": "error", "message": str(error)}), 409
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    @bp.route("/api/datasets/<dataset_id>", methods=["DELETE"])
    def delete_dataset(dataset_id):
        try:
            if state.runtime.is_active_dataset(dataset_id):
                return jsonify({"status": "error",
                                "message": "运行中的数据集不能删除，请先释放执行快照"}), 409
            return jsonify(state.dataset_workspace().delete_dataset(dataset_id))
        except FileNotFoundError:
            return jsonify({"status": "error", "message": "数据集不存在"}), 404
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    @bp.route("/api/datasets/<dataset_id>/copy", methods=["POST"])
    def copy_dataset(dataset_id):
        payload = request.get_json() or {}
        try:
            return jsonify(state.dataset_workspace().copy_dataset(
                dataset_id, payload.get("id", ""), payload.get("name", ""))), 201
        except FileNotFoundError:
            return jsonify({"status": "error", "message": "数据集不存在"}), 404
        except ConflictError as error:
            return jsonify({"status": "error", "message": str(error)}), 409
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    @bp.route("/api/datasets/import", methods=["POST"])
    def import_dataset():
        try:
            payload = request.get_json() or {}
            return jsonify(state.dataset_workspace().import_dataset(payload.get("dataset"))), 201
        except ConflictError as error:
            return jsonify({"status": "error", "message": str(error)}), 409
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    @bp.route("/api/datasets/<dataset_id>/export", methods=["GET"])
    def export_dataset(dataset_id):
        try:
            workspace = state.dataset_workspace()
            workspace.get_dataset(dataset_id)
            return send_file(workspace.dataset_dir / f"{dataset_id}.json", as_attachment=True,
                             download_name=f"{dataset_id}.json", mimetype="application/json")
        except FileNotFoundError:
            return jsonify({"status": "error", "message": "数据集不存在"}), 404
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400

    return bp
