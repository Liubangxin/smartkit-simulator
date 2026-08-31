"""Pure helpers for rendering simulated command output."""

import datetime
import random
import string


def substitute_variables(text):
    """Replace {date}/{time}/{datetime}/{sn} placeholders with live values."""
    now = datetime.datetime.now()
    sn = "".join(random.choices(string.digits, k=9))
    for k, v in {"{date}": now.strftime("%Y-%m-%d"), "{time}": now.strftime("%H:%M:%S"),
                 "{datetime}": now.strftime("%Y-%m-%d %H:%M:%S"), "{date_mmdd}": now.strftime("%m%d"),
                 "{date_yyyymmdd}": now.strftime("%Y%m%d"), "{sn}": sn}.items():
        text = text.replace(k, v)
    return text


def format_command_output(text):
    """Normalize to CRLF line endings so terminal columns align."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\r\n".join(text.rstrip("\n").split("\n")) + "\r\n"
