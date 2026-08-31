"""Runtime log API: drain the process log queue."""

import queue

from flask import Blueprint, jsonify


def register(state):
    bp = Blueprint("logs", __name__)

    @bp.route("/api/logs", methods=["GET"])
    def get_logs():
        logs = []
        while True:
            try:
                logs.append(state.log_queue.get_nowait())
            except queue.Empty:
                break
        return jsonify(logs)

    return bp
