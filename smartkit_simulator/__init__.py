"""SmartKit Simulator backend package.

Layered layout (dependency direction: api -> services -> pure helpers):

    application  - process-wide singleton state wiring every module together
    api/         - Flask blueprints (HTTP contract, parameter validation only)
    workspace/   - dataset files, case catalog/bindings, atomic writes
    runtime/     - activation snapshot and execution lease state
    ssh/  rest/  - simulated protocol servers (read the active snapshot)
    import_logs/ - execution-log parsers (SSH commands / REST routes)
    settings.py  - global settings persisted in settings.json
    legacy.py    - legacy single config.json support (/api/config, migration)
    security/    - self-signed TLS certificate generation
"""

__version__ = "1.0.0"
