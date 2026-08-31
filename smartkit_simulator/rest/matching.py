"""Pure REST route matching.

Routes match on ``HTTP method + URI``.  A single path segment may be a named
placeholder (``{session_id}``); exact URIs take priority over parameterized
ones.  These functions have no I/O and are unit-tested directly.
"""

import re
import urllib.parse

REST_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD")
REST_PATH_PARAM = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def match_rest_route(method, path, routes):
    """Return ``(route, path_parameters)`` or ``(None, {})`` when unmatched."""
    candidates = [route for route in routes if route.get("method", "GET").upper() == method]
    for route in candidates:
        if route.get("uri") == path:
            return route, {}
    for route in candidates:
        template = route.get("uri", "")
        names = []
        cursor = 0
        pattern = "^"
        for match in REST_PATH_PARAM.finditer(template):
            name = match.group(1)
            if name in names:
                pattern = ""
                break
            names.append(name)
            pattern += re.escape(template[cursor:match.start()]) + f"(?P<{name}>[^/]+)"
            cursor = match.end()
        if not names or not pattern:
            continue
        pattern += re.escape(template[cursor:]) + "$"
        matched = re.match(pattern, path)
        if matched:
            return route, {name: urllib.parse.unquote(value)
                           for name, value in matched.groupdict().items()}
    return None, {}


def substitute_path_parameters(text, parameters):
    for name, value in parameters.items():
        text = text.replace("{" + name + "}", value)
    return text
