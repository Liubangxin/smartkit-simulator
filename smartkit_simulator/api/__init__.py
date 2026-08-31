"""Flask blueprints for the management API.

Each module exposes ``register(state) -> Blueprint``.  Blueprints only do
parameter validation and HTTP encoding; domain logic lives in the service
modules (workspace / runtime / ssh / rest / import_logs / settings).
"""
