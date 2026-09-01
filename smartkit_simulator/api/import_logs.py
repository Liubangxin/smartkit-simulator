"""Execution-log import API: preview SSH commands / REST routes before importing."""

from flask import Blueprint, jsonify, request

from ..errors import WorkspaceError
from ..import_logs.rest_parser import parse_rest_routes_from_log
from ..import_logs.ssh_parser import parse_ssh_commands_from_log


def register(state):
    bp = Blueprint("import_logs", __name__)

    @bp.route("/api/ssh/import-log/preview", methods=["POST"])
    def preview_ssh_log_import():
        payload = request.get_json() or {}
        log_text = str(payload.get("log_text", ""))
        if not log_text.strip():
            return jsonify({"status": "error", "message": "Log text is required."}), 400
        parsed_commands = parse_ssh_commands_from_log(log_text)
        dataset_id = str(payload.get("dataset_id", "")).strip()
        try:
            source = (state.dataset_workspace().get_dataset(dataset_id)
                      if dataset_id else {})
        except FileNotFoundError:
            return jsonify({"status": "error", "message": "数据集不存在"}), 404
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400
        existing = {str(command.get("name", "")) for command in source.get("commands", [])}
        results = []
        for command in parsed_commands:
            name = command["name"]
            if name in existing:
                results.append({"status": "duplicate", "message": "The same command already exists.",
                                "command": command})
            else:
                results.append({"status": "ready", "message": "Ready to import.",
                                "command": command})
                existing.add(name)
        summary = {
            "total": len(results),
            "importable": sum(result["status"] == "ready" for result in results),
            "duplicate": sum(result["status"] == "duplicate" for result in results),
            # Informational: sequences that contain empty outputs (still importable).
            "incomplete": sum(1 for command in parsed_commands
                              if any(output == "" for output in command["outputs"])),
        }
        return jsonify({"status": "ok", "summary": summary, "commands": results})

    @bp.route("/api/rest/import-log/preview", methods=["POST"])
    def preview_rest_log_import():
        payload = request.get_json() or {}
        log_text = str(payload.get("log_text", ""))
        if not log_text.strip():
            return jsonify({"status": "error", "message": "Log text is required."}), 400
        parsed_routes = parse_rest_routes_from_log(log_text)
        dataset_id = str(payload.get("dataset_id", "")).strip()
        try:
            source = (state.dataset_workspace().get_dataset(dataset_id)
                      if dataset_id else {})
        except FileNotFoundError:
            return jsonify({"status": "error", "message": "数据集不存在"}), 404
        except WorkspaceError as error:
            return jsonify({"status": "error", "message": str(error)}), 400
        existing = {(str(route.get("method", "GET")).upper(), str(route.get("uri", "")))
                    for route in source.get("rest_routes", [])}
        results = []
        for route in parsed_routes:
            key = (route["method"], route["uri"])
            if route["response_body"] is None:
                results.append({"status": "missing_response", "message": "No matching response was found.",
                                "route": route})
            elif key in existing:
                results.append({"status": "duplicate", "message": "The same method and URI already exist.",
                                "route": route})
            else:
                results.append({"status": "ready", "message": "Ready to import.", "route": route})
                existing.add(key)
        summary = {
            "total": len(results),
            "importable": sum(result["status"] == "ready" for result in results),
            "duplicate": sum(result["status"] == "duplicate" for result in results),
            "incomplete": sum(result["status"] == "missing_response" for result in results),
        }
        return jsonify({"status": "ok", "summary": summary, "routes": results})

    return bp
