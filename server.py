#!/usr/bin/env python3
"""SmartKit Storage Simulator - Local SSH Server

Legacy standalone entry launched by ``run.ps1``.  The simulator logic now
lives in ``smartkit_simulator/ssh/``; this file is a thin launcher kept so
the old command line keeps working.
"""

from smartkit_simulator.ssh.standalone import main

if __name__ == "__main__":
    main()
