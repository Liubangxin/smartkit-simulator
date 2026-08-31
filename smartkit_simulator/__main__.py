"""Command-line entry point.

Run either as ``python -m smartkit_simulator`` or through the root
``simulator_gui.py`` shim (Electron, PyInstaller and docs use the latter).
"""

import argparse
import socket
import threading
import webbrowser

from werkzeug.serving import make_server

from .application import application, app


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="SmartKit Storage Simulator")
    parser.add_argument("--headless", action="store_true",
                        help="Run without browser; print SMARTKIT_READY_PORT=<port>")
    parser.add_argument("--data-dir", default=None,
                        help="Directory for writable data (settings, host key, certificates)")
    parser.add_argument("--management-port", type=int, default=None,
                        help="Fixed management port for automation; fail if unavailable")
    return parser.parse_args(argv)


def run_headless(management_port=None):
    port = 0 if management_port is None else management_port
    if not 1 <= port <= 65535 and port != 0:
        raise ValueError("management port must be between 1 and 65535")
    server = make_server("127.0.0.1", port, app, threaded=True)
    print(f"SMARTKIT_READY_PORT={server.server_port}", flush=True)
    server.serve_forever()


def main(argv=None):
    args = parse_args(argv)
    if args.data_dir:
        application.set_data_dir(args.data_dir)
    if args.headless:
        run_headless(args.management_port)
    else:
        port = 35800
        for p in range(35800, 35900):
            try:
                s = socket.socket()
                s.bind(("127.0.0.1", p))
                s.close()
                port = p
                break
            except OSError:
                continue
        url = f"http://127.0.0.1:{port}"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        print(f"GUI running at {url}")
        app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
