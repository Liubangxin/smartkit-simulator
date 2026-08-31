"""Runtime control API: health, status, activate-case, activate-dataset, release."""

from flask import Blueprint, jsonify, request

from ..errors import WorkspaceError
from ..runtime.state import RuntimeBusy


def register(state):
    bp = Blueprint("runtime", __name__)

    @bp.route("/api/runtime/health", methods=["GET"])
    def health():
        return jsonify({"status": "ready", "runtime": state.runtime.result()})

    @bp.route("/api/runtime/status", methods=["GET"])
    def status():
        return jsonify(state.runtime.result())

    @bp.route("/api/runtime/activate-case", methods=["POST"])
    def activate_case():
        payload = request.get_json() or {}
        case_id = str(payload.get("case_id", "")).strip()
        execution_id = str(payload.get("execution_id", "")).strip()
        if not case_id or not execution_id:
            return jsonify({"status": "error", "message": "case_id 和 execution_id 不能为空"}), 400
        try:
            result = state.runtime.activate_case(
                state.dataset_workspace(), case_id, execution_id, state.load_app_settings())
        except RuntimeBusy as error:
            return jsonify({"status": "error", "message": str(error),
                            "active_execution_id": error.execution_id}), 409
        except FileNotFoundError:
            return jsonify({"status": "error", "message": "绑定的数据集不存在"}), 404
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 404
        return jsonify(result)

    @bp.route("/api/runtime/release", methods=["POST"])
    def release():
        execution_id = str((request.get_json() or {}).get("execution_id", "")).strip()
        payload, http_status = state.runtime.release(execution_id)
        return jsonify(payload), http_status

    @bp.route("/api/runtime/activate-dataset", methods=["POST"])
    def activate_dataset():
        """Manually activate a dataset from the workbench without a case binding."""
        payload = request.get_json() or {}
        dataset_id = str(payload.get("dataset_id", "")).strip()
        execution_id = str(payload.get("execution_id", "")).strip()
        if not dataset_id or not execution_id:
            return jsonify({"status": "error", "message": "dataset_id 和 execution_id 不能为空"}), 400
        try:
            result = state.runtime.activate_dataset(
                state.dataset_workspace(), dataset_id, execution_id, state.load_app_settings())
        except RuntimeBusy as error:
            return jsonify({"status": "error", "message": str(error),
                            "active_execution_id": error.execution_id}), 409
        except FileNotFoundError:
            return jsonify({"status": "error", "message": "数据集不存在"}), 404
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400
        return jsonify(result)

    return bp
