"""Shared exception types for the simulator backend."""


class WorkspaceError(ValueError):
    """Domain error: invalid dataset, directory, settings or binding input."""


class ConflictError(WorkspaceError):
    """Optimistic-concurrency conflict (e.g. stale dataset revision)."""
