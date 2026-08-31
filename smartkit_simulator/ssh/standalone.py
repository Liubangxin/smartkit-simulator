"""Standalone SSH simulator entry (used by the legacy ``server.py`` / ``run.ps1``).

Preserves the old demo behavior: a fixed command set served over SSH with
hardcoded credentials, without the management API.
"""

import datetime

from .server import run_server

HOST = "127.0.0.1"
PORT = 2222
USERNAME = "admin"
PASSWORD = "admin123"


def default_commands():
    now = datetime.datetime.now()
    output = (
        "System General Information\r\n"
        "==========================\r\n"
        f"System Name: SmartKit-Storage-{now.strftime('%m%d')}\r\n"
        "Health Status: Normal\r\n"
        "Running Status: Online\r\n"
        "Total Capacity: 200.00 TB\r\n"
        f"SN: 2102350SHY10G{now.strftime('%H%M%S')}0001\r\n"
        "Location: L2\r\n"
        "Product Model: OceanStor 5510\r\n"
        "Product Version: V7R1C10\r\n"
        "Patch Version: SPC100 SPH126"
    )
    return [{
        "name": "show system general",
        "description": "Display system general information",
        "output": output,
    }]


def main():
    from ..application import application
    run_server(HOST, PORT, USERNAME, PASSWORD, default_commands(), state=application)


if __name__ == "__main__":
    main()
