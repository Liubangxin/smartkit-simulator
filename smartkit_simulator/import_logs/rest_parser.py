"""Parse ordered REST route candidates from execution logs.

Pure functions: no I/O, no global state.  Feeds the workbench "import from
log" preview flow.
"""

import json
import re
import urllib.parse

from .common import log_thread_id


def parse_rest_routes_from_log(log_text):
    """Extract ordered REST route candidates by pairing URL/result events on each log thread."""
    requests = []
    events = []
    legacy_request_pattern = re.compile(
        r"^.*?##url\s*:\s*(\S+)\s+##method\s*:\s*([A-Za-z]+).*?$", re.MULTILINE)
    http_session_request_pattern = re.compile(
        r"^.*?Sending\s+([A-Za-z]+)\s+request\s+to\s+(https?://\S+?)(?:\s+\.\.\.|\s|$).*?$",
        re.MULTILINE | re.IGNORECASE)

    request_matches = []
    for match in legacy_request_pattern.finditer(log_text):
        request_matches.append((match, match.group(1), match.group(2)))
    for match in http_session_request_pattern.finditer(log_text):
        request_matches.append((match, match.group(2), match.group(1)))

    for match, raw_url, raw_method in sorted(request_matches, key=lambda item: item[0].start()):
        method = raw_method.upper()
        parsed_url = urllib.parse.urlsplit(raw_url)
        uri = parsed_url.path or "/"
        candidate = {
            "method": method,
            "uri": uri,
            "group": "",
            "status_code": 200,
            "response_headers": {},
            "response_body": None,
        }
        requests.append(candidate)
        events.append((match.start(), "request", log_thread_id(match.group(0)), candidate))

    decoder = json.JSONDecoder()
    for marker in re.finditer(r"##result\s*:\s*", log_text):
        body_start = marker.end()
        source = log_text[body_start:]
        leading = len(source) - len(source.lstrip())
        try:
            value, consumed = decoder.raw_decode(source.lstrip())
        except json.JSONDecodeError:
            continue
        body_end = body_start + leading + consumed
        line_end = log_text.find("\n", body_end)
        tail = log_text[body_end:line_end if line_end >= 0 else len(log_text)]
        events.append((marker.start(), "result", log_thread_id(tail), value))

    received_pattern = re.compile(
        r"^.*?Received\s+([A-Za-z]+)\s+response\s+successfully\s+from\s+"
        r"(https?://\S+?)[.]?\s+\([^\r\n]*?$", re.MULTILINE | re.IGNORECASE)
    for match in received_pattern.finditer(log_text):
        parsed_url = urllib.parse.urlsplit(match.group(2))
        events.append((match.start(), "received", log_thread_id(match.group(0)),
                       (match.group(1).upper(), parsed_url.path or "/")))

    response_info_pattern = re.compile(r"ResponseInfo\s*:\s*", re.IGNORECASE)
    for marker in response_info_pattern.finditer(log_text):
        source = log_text[marker.end():]
        leading = len(source) - len(source.lstrip())
        try:
            value, _consumed = decoder.raw_decode(source.lstrip())
        except json.JSONDecodeError:
            continue
        line_end = log_text.find("\n", marker.end())
        line = log_text[marker.start():line_end if line_end >= 0 else len(log_text)]
        events.append((marker.start(), "response_info", log_thread_id(line), value))

    pending = {}
    completed = {}
    for _position, event_type, thread_id, value in sorted(events, key=lambda event: event[0]):
        if event_type == "request":
            pending[thread_id] = value
        elif event_type == "result" and thread_id in pending:
            route = pending.pop(thread_id)
            route["response_body"] = json.dumps(value, indent=2, ensure_ascii=False)
            route["response_headers"] = {"Content-Type": "application/json"}
            completed[thread_id] = route
        elif event_type == "received" and thread_id in pending:
            route = pending[thread_id]
            if (route["method"], route["uri"]) == value:
                pending.pop(thread_id)
                route["response_body"] = "{}"
                completed[thread_id] = route
        elif event_type == "response_info" and thread_id in completed:
            route = completed[thread_id]
            route["response_body"] = json.dumps(value, indent=2, ensure_ascii=False)
            route["response_headers"] = {"Content-Type": "application/json"}
    return requests
