"""Parse SSH commands (and their terminal outputs) from execution logs.

Pure functions: no I/O, no global state.  Feeds the workbench "import from
log" preview flow.
"""

import re

from .common import log_thread_id


def clean_ssh_received_output(command, body):
    """Strip echo, prompt and Java frame suffixes from a Receive body.

    Blank lines and trailing spaces *inside* the captured output (before the
    prompt line) are preserved; only the command echo line, the ``xxx:/>``
    prompt line, the Java metadata frame and any blank lines left after the
    removed prompt line are dropped.
    """
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # Remove the trailing Java frame (e.g. "(SshConnection.java:1513)
    # [thread-a](pid-1)") from the last non-empty line — usually the prompt
    # line.  Any other trailing spaces on that line stay untouched.
    last = len(lines) - 1
    while last >= 0 and not lines[last].strip():
        last -= 1
    if last < 0:
        return ""
    lines[last] = re.sub(
        r"\s*\(SshConnection\.java:\d+\)\s*\[[^\]]+\](?:\(pid-[^)]+\))?\s*$",
        "", lines[last])

    # Drop the prompt line plus whatever blank lines trail it: that line is a
    # log-tool artifact, and the blank lines after it are capture boundaries,
    # not device output.
    if re.fullmatch(r"[^\r\n]*:/>\s*", lines[last]):
        del lines[last:]

    # Drop the command echo: the first non-empty line that repeats the
    # command name.  Blank lines before it are preserved.
    for index, line in enumerate(lines):
        if line.strip():
            if line.strip() == command:
                del lines[index]
            break

    return "\n".join(lines)


def parse_ssh_commands_from_log(log_text):
    """Extract SSH commands and pair multiline Receive responses from execution logs.

    Multiple executions of the same command are merged into a single entry
    whose ``outputs`` list preserves the log order; executions without a
    captured response contribute an empty string so the sequence stays
    complete and importable.
    """
    execute_pattern = re.compile(
        r"^.*?Execute command line\s*:\s*(.*?)\s*,\s*timeout is\s*:\s*\d+.*?$",
        re.MULTILINE)
    occurrences = []
    for match in execute_pattern.finditer(log_text):
        name = match.group(1).strip()
        occurrences.append({
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
        eligible = [entry for entry in occurrences
                    if entry["position"] < match.start()
                    and entry["command"]["name"] == name
                    and entry["command"]["output"] is None]
        if thread_id:
            same_thread = [entry for entry in eligible if entry["thread_id"] == thread_id]
            if same_thread:
                eligible = same_thread
        if eligible:
            eligible[-1]["command"]["output"] = clean_ssh_received_output(name, match.group(2))

    grouped = {}
    order = []
    for entry in occurrences:
        command = entry["command"]
        name = command["name"]
        if name not in grouped:
            grouped[name] = {"name": name, "description": "从日志导入", "group": "", "outputs": []}
            order.append(name)
        output = command["output"]
        grouped[name]["outputs"].append(output if output is not None else "")
    result = []
    for name in order:
        entry = grouped[name]
        # Mirror the first output into the legacy single-output field.
        entry["output"] = entry["outputs"][0] if entry["outputs"] else ""
        result.append(entry)
    return result
