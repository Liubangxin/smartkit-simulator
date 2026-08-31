"""Legacy single ``config.json`` support.

This is the pre-dataset storage format.  It is kept as the migration source
and as the fallback runtime config when no dataset snapshot is active
(``GET/POST /api/config``, ``load_config``).  New data lives in dataset
files; this module must not grow new behavior.
"""

import json
import os

from .paths import resource_path
from .settings import DEFAULT_REST_SERVER, DEFAULT_SERVER


def normalize_groups(config):
    """Deduplicate explicit group lists and collect groups referenced by items."""
    for list_key, item_key in (("command_groups", "commands"), ("rest_groups", "rest_routes")):
        groups = []
        for name in config.get(list_key, []):
            name = str(name).strip()
            if name and name != "Ungrouped" and name not in groups:
                groups.append(name)
        for item in config.get(item_key, []):
            name = str(item.get("group", "")).strip()
            if name and name != "Ungrouped" and name not in groups:
                groups.append(name)
        config[list_key] = groups
    return config


def load_config(state):
    config_path = state.config_path if os.path.exists(state.config_path) else resource_path("config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        config["server"] = {**DEFAULT_SERVER, **config.get("server", {})}
        config["rest_server"] = {**DEFAULT_REST_SERVER, **config.get("rest_server", {})}
        config.setdefault("commands", [])
        config.setdefault("rest_routes", [])
        return normalize_groups(config)
    return {"server": dict(DEFAULT_SERVER), "commands": [], "command_groups": [],
            "rest_server": dict(DEFAULT_REST_SERVER), "rest_routes": [], "rest_groups": []}


def save_config(state, config):
    config = normalize_groups(config)
    with open(state.config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
