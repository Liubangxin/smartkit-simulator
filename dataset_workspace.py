"""Persistent, one-file dataset workspace for SmartKit Simulator.

Backward-compatible re-export shim: the implementation moved into
``smartkit_simulator.workspace.store`` during the package refactor.
"""

from smartkit_simulator.errors import ConflictError, WorkspaceError
from smartkit_simulator.workspace.store import (DATASET_ID, DatasetWorkspace,
                                                _WORKSPACE_LOCK, _atomic_json)

__all__ = [
    "ConflictError",
    "DatasetWorkspace",
    "WorkspaceError",
    "DATASET_ID",
    "_atomic_json",
    "_WORKSPACE_LOCK",
]
