"""Paramiko-based SSH simulator serving configured command responses.

The server reads the *active* command set through ``command_provider`` so the
workbench can save new responses while a session is running without restarting
the listener.
"""

import os
import socket
import threading

import paramiko

from .rendering import format_command_output, substitute_variables


class SimulatorServer(paramiko.ServerInterface):
    def __init__(self, username, password, commands, command_provider=None, log_queue=None):
        self._username, self._password, self._commands = username, password, commands
        self._command_provider = command_provider or (lambda: self._commands)
        self._log_queue = log_queue

    def _log(self, text):
        if self._log_queue is not None:
            self._log_queue.put(text)

    def check_auth_password(self, username, password):
        return (paramiko.AUTH_SUCCESSFUL
                if username == self._username and password == self._password
                else paramiko.AUTH_FAILED)

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_shell_request(self, channel):
        threading.Thread(target=self._handle_shell, args=(channel,), daemon=True).start()
        return True

    def check_channel_exec_request(self, channel, command):
        cmd = command.decode("utf-8").strip()
        threading.Thread(target=self._handle_exec, args=(channel, cmd), daemon=True).start()
        return True

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True

    def _current_commands(self):
        try:
            return self._command_provider()
        except Exception as e:
            self._log(f"[error] Cannot load commands: {e}")
            return self._commands

    def _lookup(self, name):
        for c in self._current_commands():
            if c["name"] == name:
                return c
        return None

    def _handle_shell(self, channel):
        try:
            channel.send(b"SmartKit Storage Simulator\r\nType 'help' for available commands.\r\n\r\nsmartkit:/>")
            buf = b""
            while not channel.closed:
                try:
                    data = channel.recv(1024)
                except Exception:
                    continue
                if not data:
                    continue
                for b in data:
                    if b in (0x7f, 0x08):
                        if buf:
                            buf = buf[:-1]
                            channel.send(b"\b \b")
                        continue
                    channel.send(bytes([b]))
                    if b in (0x0d, 0x0a):
                        if b == 0x0d:
                            channel.send(b"\n")
                        cmd = buf.decode("utf-8", errors="replace").strip()
                        buf = b""
                        self._log(f"shell: {cmd}" if cmd else "shell: <empty>")
                        if cmd in ("exit", "quit"):
                            channel.send(b"Goodbye.\r\n")
                            channel.close()
                            return
                        if cmd == "help":
                            channel.send(b"Available commands:\r\n")
                            for c in self._current_commands():
                                channel.send(f"  {c['name']:<28s} - {c.get('description','')}\r\n".encode())
                            channel.send(b"  exit / quit           - Close this session\r\n")
                            channel.send(b"  help                  - Show this help\r\n")
                        else:
                            entry = self._lookup(cmd)
                            if entry:
                                channel.send(format_command_output(substitute_variables(entry["output"])).encode())
                            elif cmd:
                                channel.send(f"Unknown command: {cmd}\r\n".encode())
                                channel.send(b"Type 'help' for available commands.\r\n")
                        channel.send(b"smartkit:/>")
                        continue
                    buf += bytes([b])
        except (EOFError, OSError):
            pass
        finally:
            channel.close()

    def _handle_exec(self, channel, command):
        try:
            self._log(f"exec: {command}")
            entry = self._lookup(command)
            if entry:
                channel.send(format_command_output(substitute_variables(entry["output"])).encode())
            else:
                channel.send(f"Unknown command: {command}\r\n".encode())
            channel.send_exit_status(0)
        except Exception:
            channel.send_exit_status(1)
        finally:
            channel.close()


def run_server(bind_address, port, username, password, commands, server_stop_event=None, *, state=None):
    """Run the SSH simulator until the stop event is set.

    ``state`` defaults to the process-wide application state; tests can pass
    their own or rely on ``simulator_gui.stop_event`` sharing the same object.
    """
    if state is None:
        from ..application import application as default_state
        state = default_state
    bind_address = (bind_address or "127.0.0.1").strip() or "127.0.0.1"
    stop_signal = server_stop_event or state.stop_event
    if not os.path.exists(state.host_key_path):
        paramiko.RSAKey.generate(2048).write_private_key_file(state.host_key_path)
    host_key = paramiko.RSAKey(filename=state.host_key_path)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(1.0)
    try:
        sock.bind((bind_address, port))
    except OSError as e:
        state.log_queue.put(f"[error] Cannot bind {bind_address}:{port}: {e}")
        return
    sock.listen(5)
    state.log_queue.put(f"Server listening on {bind_address}:{port}")
    while not stop_signal.is_set():
        try:
            client, addr = sock.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        state.log_queue.put(f"Connection from {addr[0]}:{addr[1]}")
        transport = paramiko.Transport(client)
        transport.add_server_key(host_key)
        server = SimulatorServer(username, password, commands,
                                 lambda: state.active_config().get("commands", []),
                                 log_queue=state.log_queue)
        try:
            transport.start_server(server=server)
        except paramiko.SSHException as e:
            state.log_queue.put(f"[error] SSH negotiation: {e}")
            continue

        def wait_transport(t):
            channels = []
            try:
                while t.is_active():
                    chan = t.accept(1)
                    if chan is not None:
                        channels.append(chan)
                    channels[:] = [chan for chan in channels if not chan.closed]
            except (EOFError, OSError):
                pass

        threading.Thread(target=wait_transport, args=(transport,), daemon=True).start()
    sock.close()
    state.log_queue.put("Server stopped")


def stop_server_thread(state, timeout=3.0):
    """Signal the SSH server loop to stop and wait for the thread to exit."""
    state.stop_event.set()
    if state.server_thread and state.server_thread.is_alive():
        state.server_thread.join(timeout)
        if state.server_thread.is_alive():
            state.log_queue.put("[error] Previous server did not stop in time")
            return False
    state.server_thread = None
    return True
