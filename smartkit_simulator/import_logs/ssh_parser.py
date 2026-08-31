"""Parse SSH commands (and their terminal outputs) from execution logs.

Pure functions: no I/O, no global state.  Feeds the workbench "import from
log" preview flow.
"""

import re

from .common import log_thread_id


def clean_ssh_received_output(command, body):
    """Strip echo, prompt and Java frame suffixes from a Receive body."""
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        lines[-1] = re.sub(
            r"\s*\(SshConnection\.java:\d+\)\s*\[[^\]]+\](?:\(pid-[^)]+\))?\s*$",
            "", lines[-1]).rstrip()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and re.fullmatch(r"[^\r\n]*:/>\s*", lines[-1]):
        lines.pop()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[0].strip() == command:
        lines.pop(0)
    return "\n".join(lines).strip()


def parse_ssh_commands_from_log(log_text):
    """Extract SSH commands and pair multiline Receive responses from execution logs."""
    execute_pattern = re.compile(
        r"^.*?Execute command line\s*:\s*(.*?)\s*,\s*timeout is\s*:\s*\d+.*?$",
        re.MULTILINE)
    commands = []
    for match in execute_pattern.finditer(log_text):
        name = match.group(1).strip()
        commands.append({
            "position": match.start(),
            "thread_id": log_thread_id(match.group(0)),
            "command": {"name": name, "description": "从日志导入", "group": "", "output": None},
        })

    receive_pattern = re.compile(
        r"^[^\r\n]*?\[(?:INFO|WARN|ERROR|DEBUG)\]\s+Receive str\s*:\s*([^\r\n]*)\r?\n"
        r"(.*?)(?=^\d{4}-\d{2}-\d{2}[^\r\n]*\[(?:INFO|WARN|ERROR|DEBUG)\]|\Z)",
        re.MULTILINE | re.DOTALL)
    for match in receive_pattern.finditer(log_text):
        name = match.group(1).strip()
        thread_id = log_thread_id(match.group(0))
        eligible = [entry for entry in commands
                    if entry["position"] < match.start()
                    and entry["command"]["name"] == name
                    and entry["command"]["output"] is None]
        if thread_id:
            same_thread = [entry for entry in eligible if entry["thread_id"] == thread_id]
            if same_thread:
                eligible = same_thread
        if eligible:
            eligible[-1]["command"]["output"] = clean_ssh_received_output(name, match.group(2))
    return [entry["command"] for entry in commands]
