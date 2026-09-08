"""Runtime snapshot and execution lease state.

Only one active snapshot may exist at a time.  Activating copies the dataset
(a deep, immutable snapshot); later workbench edits never affect a running
execution.  ``RuntimeState`` owns the lock, so the API layer never touches
the snapshot dict directly.

When no snapshot is active the protocol simulators serve an *empty* config:
SSH answers ``Unknown command`` and REST returns 404.  Simulated data only
ever comes from an activated dataset.
"""

import copy
import datetime
import hashlib
import json
import os
import threading

from ..errors import WorkspaceError

#: Idle fallback served by SSH/REST when no dataset snapshot is active.
EMPTY_CONFIG = {"commands": [], "command_groups": [],
                "rest_routes": [], "rest_groups": []}


class RuntimeBusy(WorkspaceError):
    """Another execution holds the simulator instance (409)."""

    def __init__(self, execution_id):
        super().__init__("模拟器实例正被其他执行占用")
        self.execution_id = execution_id


class RuntimeState:
    def __init__(self, data_dir):
        self._lock = threading.Lock()
        self._snapshot = None
        self.data_dir = data_dir

    # ------------------------------------------------------------------ queries

    def result(self, include_snapshot=False):
        """Public runtime status dict (never leaks the internal snapshot)."""
        with self._lock:
            if not self._snapshot:
                return {"status": "idle"}
            result = {key: value for key, value in self._snapshot.items() if key != "snapshot"}
            snapshot = self._snapshot.get("snapshot") or {}
            result["dataset_name"] = str(snapshot.get("name") or result.get("dataset_id") or "")
            result["command_count"] = len(snapshot.get("commands") or [])
            result["route_count"] = len(snapshot.get("rest_routes") or [])
            if include_snapshot:
                result["snapshot"] = copy.deepcopy(self._snapshot["snapshot"])
            return result

    def active_config(self):
        """Dataset served by the protocol simulators: snapshot or empty config."""
        with self._lock:
            if self._snapshot:
                return copy.deepcopy(self._snapshot["snapshot"])
        return copy.deepcopy(EMPTY_CONFIG)

    def is_active_dataset(self, dataset_id):
        with self._lock:
            return bool(self._snapshot and self._snapshot.get("dataset_id") == dataset_id)

    def is_active_dataset(self, dataset_id):
        with self._lock:
            return bool(self._snapshot and self._snapshot.get("dataset_id") == dataset_id)

    def reset(self):
        with self._lock:
            self._snapshot = None

    # --------------------------------------------------------------- lifecycle

    def activate_case(self, workspace, case_id, execution_id, settings):
        """Activate the dataset bound to ``case_id``; idempotent per execution.

        Returns the public activation result.  Raises ``RuntimeBusy`` when
        another execution holds the instance, ``FileNotFoundError`` when the
        bound dataset is missing, ``WorkspaceError`` for other domain errors.
        """
        with self._lock:
            if self._snapshot:
                if (self._snapshot["execution_id"] == execution_id
                        and self._snapshot["case_id"] == case_id):
                    return {key: value for key, value in self._snapshot.items() if key != "snapshot"}
                raise RuntimeBusy(self._snapshot["execution_id"])
            dataset_id, dataset = workspace.resolve_case(case_id)
            self._snapshot = self._build_snapshot(dataset_id, dataset, case_id, execution_id, settings)
            result = {key: value for key, value in self._snapshot.items() if key != "snapshot"}
        self._persist()
        return result

    def activate_dataset(self, workspace, dataset_id, execution_id, settings):
        """Manually activate a dataset from the workbench (no case binding).

        Mirrors the original API: this variant does not persist ``active.json``.
        """
        with self._lock:
            if self._snapshot:
                raise RuntimeBusy(self._snapshot["execution_id"])
            dataset = workspace.get_dataset(dataset_id)
            self._snapshot = self._build_snapshot(dataset_id, dataset, "manual",
                                                  execution_id, settings)
            result = {key: value for key, value in self._snapshot.items() if key != "snapshot"}
        return result

    def release(self, execution_id):
        """Release the lease.  Returns ``(payload, http_status)``."""
        with self._lock:
            if not self._snapshot:
                return {"status": "idle"}, 200
            if execution_id != self._snapshot["execution_id"]:
                return {"status": "error", "message": "execution_id 不是当前租约持有者"}, 409
            self._snapshot = None
        runtime_path = os.path.join(self.data_dir, "runtime", "active.json")
        if os.path.exists(runtime_path):
            os.unlink(runtime_path)
        return {"status": "released", "execution_id": execution_id}, 200

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _build_snapshot(dataset_id, dataset, case_id, execution_id, settings):
        canonical = json.dumps(dataset, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")
        server = settings["ssh_server"]
        rest = settings["rest_server"]
        return {
            "status": "active", "case_id": case_id, "execution_id": execution_id,
            "dataset_id": dataset_id, "dataset_file": f"{dataset_id}.json",
            "dataset_revision": dataset["revision"],
            "checksum": "sha256:" + hashlib.sha256(canonical).hexdigest(),
            "activated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "ssh_endpoint": f"{server['bind_address']}:{server['port']}",
            "rest_endpoint": f"https://{rest['bind_address']}:{rest['port']}",
            "snapshot": copy.deepcopy(dataset),
        }

    def _persist(self):
        runtime_path = os.path.join(self.data_dir, "runtime", "active.json")
        os.makedirs(os.path.dirname(runtime_path), exist_ok=True)
        with open(runtime_path, "w", encoding="utf-8") as stream:
            json.dump(self._snapshot, stream, ensure_ascii=False, indent=2)
