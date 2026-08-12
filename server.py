#!/usr/bin/env python3
"""SmartKit Storage Simulator - Local SSH Server"""

import paramiko
import socket
import threading
import time
import os
import datetime

# ---- Configuration ----
HOST = "127.0.0.1"
PORT = 2222
USERNAME = "admin"
PASSWORD = "admin123"
HOST_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "host_key")

start_time = time.time()


# ---- Command handlers ----

def cmd_show_system_general(channel):
    """show system general"""
    now = datetime.datetime.now()
    lines = [
        "System General Information",
        "==========================",
        f"System Name: SmartKit-Storage-{now.strftime('%m%d')}",
        f"Health Status: Normal",
        f"Running Status: Online",
        f"Total Capacity: 200.00 TB",
        f"SN: 2102350SHY10G{now.strftime('%H%M%S')}0001",
        f"Location: L2",
        f"Product Model: OceanStor 5510",
        f"Product Version: V7R1C10",
        f"Patch Version: SPC100 SPH126"
    ]
    channel.send(("\r\n".join(lines) + "\r\n").encode("utf-8"))

_COMMANDS = {
    "show system general": (cmd_show_system_general, "Display system general information"),
}


class StorageSimulatorServer(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        if username == USERNAME and password == PASSWORD:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_shell_request(self, channel):
        threading.Thread(target=handle_shell, args=(channel,), daemon=True).start()
        return True

    def check_channel_exec_request(self, channel, command):
        cmd = command.decode("utf-8").strip()
        threading.Thread(target=handle_exec, args=(channel, cmd), daemon=True).start()
        return True

    def check_channel_pty_request(
        self, channel, term, width, height, pixelwidth, pixelheight, modes
    ):
        return True


def handle_shell(channel):
    """Interactive shell with echo and backspace support."""
    try:
        channel.send(b"SmartKit Storage Simulator v2.3.1 (echo+bs)\r\n")
        channel.send(b"Type 'help' for available commands.\r\n\r\n")
        channel.send(b"smartkit:/> ")
        buf = b""
        while not channel.closed:
            try:
                data = channel.recv(1024)
            except Exception:
                continue
            if not data:
                continue
            for b in data:
                # Backspace (DEL 0x7f / BS 0x08)
                if b == 0x7f or b == 0x08:
                    if buf:
                        buf = buf[:-1]
                        channel.send(b"\b \b")
                    continue
                # Echo the character
                channel.send(bytes([b]))
                # Line terminator
                if b in (0x0d, 0x0a):
                    if b == 0x0d:
                        channel.send(b"\n")
                    cmd = buf.decode("utf-8", errors="replace").strip()
                    buf = b""
                    if cmd in ("exit", "quit"):
                        channel.send(b"Goodbye.\r\n")
                        channel.close()
                        return
                    if cmd == "help":
                        channel.send(b"Available commands:\r\n")
                        for name, (_, desc) in _COMMANDS.items():
                            channel.send(f"  {name:<28s} - {desc}\r\n".encode("utf-8"))
                        channel.send(b"  exit / quit           - Close this session\r\n")
                        channel.send(b"  help                  - Show this help\r\n")
                    elif cmd in _COMMANDS:
                        _COMMANDS[cmd][0](channel)
                    elif cmd:
                        channel.send(f"Unknown command: {cmd}\r\n".encode("utf-8"))
                        channel.send(b"Type 'help' for available commands.\r\n")
                    channel.send(b"smartkit:/> ")
                    continue
                # Normal character
                buf += bytes([b])
    except (EOFError, OSError):
        pass
    except Exception as e:
        print(f"[!] Shell error: {e}")
    finally:
        channel.close()


def handle_exec(channel, command):
    try:
        if command in _COMMANDS:
            _COMMANDS[command][0](channel)
        else:
            channel.send(f"Unknown command: {command}\r\n".encode("utf-8"))
        channel.send_exit_status(0)
    except Exception as e:
        print(f"[!] Exec error: {e}")
        channel.send_exit_status(1)
    finally:
        channel.close()


def generate_host_key():
    if not os.path.exists(HOST_KEY_PATH):
        print("[*] Generating new host key...")
        key = paramiko.RSAKey.generate(2048)
        key.write_private_key_file(HOST_KEY_PATH)
        print(f"[+] Host key saved to {HOST_KEY_PATH}")
    else:
        print(f"[*] Using existing host key: {HOST_KEY_PATH}")


def start_server():
    generate_host_key()
    host_key = paramiko.RSAKey(filename=HOST_KEY_PATH)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, PORT))
    sock.listen(100)

    print(f"[+] SSH server listening on {HOST}:{PORT}")
    print(f"    Username: {USERNAME}")
    print(f"    Password: {PASSWORD}")
    print(f"    Connect:  ssh {USERNAME}@{HOST} -p {PORT}")
    print()

    def handle_client(client, addr):
        print(f"[*] Connection from {addr[0]}:{addr[1]}")
        transport = paramiko.Transport(client)
        transport.add_server_key(host_key)
        server = StorageSimulatorServer()
        try:
            transport.start_server(server=server)
        except paramiko.SSHException as e:
            print(f"[!] SSH negotiation failed: {e}")
            return
        try:
            while transport.is_active():
                chan = transport.accept(1)
                if chan is not None:
                    pass
        except (EOFError, OSError):
            pass

    while True:
        client, addr = sock.accept()
        threading.Thread(target=handle_client, args=(client, addr), daemon=True).start()


if __name__ == "__main__":
    start_server()
