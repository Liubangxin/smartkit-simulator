"""Project root and resource path resolution.

Works for source runs, ``--data-dir`` overrides and PyInstaller one-file
builds (``sys._MEIPASS``).  The writable data directory itself lives on the
``ApplicationState`` because it can change at runtime via ``set_data_dir``.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(relative_path):
    """Resolve a bundled resource (HTML, config) against the frozen bundle
    when running under PyInstaller, otherwise against the project root."""
    base = getattr(sys, "_MEIPASS", BASE_DIR)
    return os.path.join(base, relative_path)
