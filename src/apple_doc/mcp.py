"""`apple-doc --mcp`: a Model Context Protocol server over stdio, standard library only.

A thin layer over the same search and render code the CLI uses. It speaks both eras of MCP:

* modern (2026-07-28): stateless; every request carries its protocol version and client
  capabilities in ``params._meta``; ``server/discover`` describes the server;
* legacy (2025-11-25 and earlier): an ``initialize`` handshake picks the version for the
  rest of the process, followed by ``notifications/initialized``.

Framing is newline-delimited JSON-RPC 2.0 on stdin/stdout. Nothing but protocol messages is
written to stdout; the one log line goes to stderr.
"""

from __future__ import annotations

import json
import sys

from apple_doc import __version__
from apple_doc.errors import AppleDocError
from apple_doc.index import REBUILD_HINT
from apple_doc.search import format_page, format_search, get_page, list_frameworks, search

MODERN_VERSIONS = ["2026-07-28"]
LEGACY_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CAPS = "io.modelcontextprotocol/clientCapabilities"
SERVER_INFO = {
    "name": "apple-doc",
    "title": "Apple developer documentation",
    "version": __version__,
}

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = (
    -32700,
    -32600,
    -32601,
    -32602,
    -32603,
)
UNSUPPORTED_VERSION = -32022

READ_LINES = 80
MAX_LIMIT = 10

INSTRUCTIONS = (
    "Offline search of Apple's developer documentation (every framework, plus the Human "
    "Interface Guidelines). Check an Apple API here before relying on how it behaves. The "
    "search matches words, not meaning: pass class, method, notification or topic names "
    "(e.g. 'NSTextView undo textDidChange', framework 'AppKit'), not sentences. Run 2-3 small "
    "searches, then read one page with read_apple_doc."
)

_READ_ONLY = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}

TOOLS = [
    {
        "name": "search_apple_docs",
        "title": "Search Apple developer docs",
        "description": (
            "Search Apple's developer documentation offline and get a few ranked hits, each "
            "with framework, macOS availability, declaration, the best-matching lines and the "
            "page path. Keyword search: put API names and Apple's own terms in the query, not "
            "a sentence. 'store a password securely' -> 'Keychain SecItemAdd generic password'; "
            "'images in my HTML don't load' -> 'WKWebView loadHTMLString baseURL relative'. "
            "Don't know the API? Search the topic words, open the overview article with "
            "read_apple_doc, then search the symbol names it mentions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "API names and topic words, e.g. 'NSTextView undo'",
                },
                "framework": {
                    "type": "string",
                    "description": "Only this framework, e.g. 'AppKit', 'WebKit', 'SwiftUI', "
                    "'Human Interface Guidelines'. Omit to search everything (articles shared "
                    "across platforms are often filed under UIKit or SwiftUI).",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_LIMIT,
                    "default": 3,
                    "description": "Number of hits (default 3)",
                },
                "any_platform": {
                    "type": "boolean",
                    "default": False,
                    "description": "Don't prefer macOS-available symbols (use for iOS-only APIs)",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "read_apple_doc",
        "title": "Read an Apple developer doc page",
        "description": (
            "Read one documentation page or section: the path shown under a search hit (e.g. "
            "'/documentation/AppKit/NSView/updateLayer()'), a developer.apple.com URL, or a "
            "page's unique last segment. Returns up to 80 lines, then the page's availability "
            "and its section anchors; long articles keep their content in sections, so pass "
            "one as 'section' to read it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Page path or URL from a search hit"},
                "section": {
                    "type": "string",
                    "description": "Optional section anchor listed at the end of a page, "
                    "e.g. 'Update-custom-views-using-specific-methods'",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "list_frameworks",
        "title": "List documentation frameworks",
        "description": "List the framework names search_apple_docs accepts as 'framework', "
        "with page counts.",
        "inputSchema": {"type": "object", "additionalProperties": False},
        "annotations": _READ_ONLY,
    },
]


def log(msg: str) -> None:
    print("apple-doc mcp: " + msg, file=sys.stderr, flush=True)


class ToolInputError(Exception):
    """Bad arguments a model can fix: reported as a tool result with isError."""


def _text(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _arg(args: dict, name: str, kind, default=None):
    value = args.get(name, default)
    if value is None:
        return default
    if kind is int and isinstance(value, bool) or not isinstance(value, kind):
        raise ToolInputError("'%s' must be a %s" % (name, kind.__name__))
    return value


def _search(args: dict) -> dict:
    query = _arg(args, "query", str)
    if not query or not query.strip():
        raise ToolInputError("'query' is required: pass API names or topic words")
    framework = _arg(args, "framework", str)
    limit = _arg(args, "limit", int, 3)
    if not 1 <= limit <= MAX_LIMIT:
        raise ToolInputError("'limit' must be between 1 and %d" % MAX_LIMIT)
    any_platform = _arg(args, "any_platform", bool, False)
    res = search(query, framework, limit, 4, any_platform)
    text = format_search(res, 60)
    if res.stale:
        text = REBUILD_HINT.removeprefix("apple-doc: ") + "\n\n" + text
    if not res.hits:
        text += "\nNo hits: rephrase with other API names or topic words, or drop 'framework'."
    return _text(text)


def _read(args: dict) -> dict:
    path = _arg(args, "path", str)
    if not path or not path.strip():
        raise ToolInputError("'path' is required, e.g. /documentation/AppKit/NSView")
    section = _arg(args, "section", str)
    if section:
        path = path.split("#")[0] + "#" + section.lstrip("#")
    return _text(format_page(get_page(path), READ_LINES))


def _frameworks(args: dict) -> dict:
    rows = list_frameworks()
    return _text("\n".join("%s (%d)" % (f, n) for f, n in rows))


HANDLERS = {"search_apple_docs": _search, "read_apple_doc": _read, "list_frameworks": _frameworks}


class RPCError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


class Server:
    def __init__(self) -> None:
        self.legacy_version: str | None = None  # set by a legacy initialize

    # -- dispatch --------------------------------------------------------------------------

    def handle(self, msg) -> dict | None:
        """One parsed JSON-RPC message in, one response (or None for notifications) out."""
        if not isinstance(msg, dict):
            return _error(
                None, INVALID_REQUEST, "expected a JSON-RPC object (batches are not supported)"
            )
        has_id = "id" in msg
        req_id = msg.get("id")
        method = msg.get("method")
        if "method" not in msg and ("result" in msg or "error" in msg):
            return None  # a response from the client; this server sends no requests
        if msg.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return _error(
                req_id if _valid_id(req_id) else None,
                INVALID_REQUEST,
                "invalid JSON-RPC 2.0 request",
            )
        if not has_id:
            return None  # notifications (initialized, cancelled, ...) need no reply
        if not _valid_id(req_id):
            return _error(None, INVALID_REQUEST, "request id must be a string or integer")
        params = msg.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return _error(req_id, INVALID_PARAMS, "params must be an object")
        try:
            result = self.dispatch(method, params)
        except RPCError as e:
            return _error(req_id, e.code, e.message, e.data)
        except Exception as e:  # never let one request kill the server
            log("internal error in %s: %r" % (method, e))
            return _error(req_id, INTERNAL_ERROR, "internal error: %s" % e)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def dispatch(self, method: str, params: dict) -> dict:
        if method == "initialize":
            return self.initialize(params)
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        modern = META_VERSION in meta
        if method == "server/discover":
            return self.discover()
        if method == "ping":
            return self.complete({}, modern)
        if modern:
            self.check_modern(meta)
        elif self.legacy_version is None:
            raise RPCError(
                INVALID_PARAMS,
                "missing _meta '%s' (protocol %s), or send initialize first (protocol %s)"
                % (META_VERSION, MODERN_VERSIONS[0], ", ".join(LEGACY_VERSIONS)),
            )
        if method == "tools/list":
            return self.complete({"tools": TOOLS}, modern)
        if method == "tools/call":
            return self.complete(self.call_tool(params), modern)
        raise RPCError(METHOD_NOT_FOUND, "method not found: %s" % method)

    # -- protocol pieces -------------------------------------------------------------------

    def initialize(self, params: dict) -> dict:
        requested = params.get("protocolVersion")
        if requested in MODERN_VERSIONS:
            requested = LEGACY_VERSIONS[0]  # initialize is legacy-only; answer in legacy terms
        version = requested if requested in LEGACY_VERSIONS else LEGACY_VERSIONS[0]
        self.legacy_version = version
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        }

    def discover(self) -> dict:
        return {
            "resultType": "complete",
            "supportedVersions": MODERN_VERSIONS + LEGACY_VERSIONS,
            "capabilities": {"tools": {"listChanged": False}},
            "instructions": INSTRUCTIONS,
            "_meta": {"io.modelcontextprotocol/serverInfo": SERVER_INFO},
        }

    def check_modern(self, meta: dict) -> None:
        version = meta.get(META_VERSION)
        if version not in MODERN_VERSIONS:
            raise RPCError(
                UNSUPPORTED_VERSION,
                "Unsupported protocol version",
                {"supported": MODERN_VERSIONS + LEGACY_VERSIONS, "requested": version},
            )
        if not isinstance(meta.get(META_CAPS), dict):
            raise RPCError(INVALID_PARAMS, "missing _meta '%s'" % META_CAPS)

    def complete(self, result: dict, modern: bool) -> dict:
        result = dict(result)
        result["resultType"] = "complete"
        if modern:
            result["_meta"] = {"io.modelcontextprotocol/serverInfo": SERVER_INFO}
        return result

    def call_tool(self, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments", {})
        if args is None:
            args = {}
        if not isinstance(name, str) or name not in HANDLERS:
            raise RPCError(INVALID_PARAMS, "unknown tool: %s" % name)
        if not isinstance(args, dict):
            raise RPCError(INVALID_PARAMS, "tool arguments must be an object")
        known = set(
            next(t for t in TOOLS if t["name"] == name)["inputSchema"].get("properties", {})
        )
        extra = sorted(set(args) - known)
        try:
            if extra:
                raise ToolInputError(
                    "unknown argument(s): %s; expected: %s"
                    % (", ".join(extra), ", ".join(sorted(known)) or "none")
                )
            return HANDLERS[name](args)
        except ToolInputError as e:
            return _text(str(e), is_error=True)
        except AppleDocError as e:
            return _text(str(e), is_error=True)


def _valid_id(value) -> bool:
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


def _error(req_id, code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def encode(msg: dict) -> str:
    """One line of JSON: json.dumps escapes newlines inside strings, so framing holds."""
    return json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n"


def handle_line(server: Server, line: bytes) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        msg = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        return _error(None, PARSE_ERROR, "parse error: %s" % e)
    return server.handle(msg)


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout
    sys.stdout = sys.stderr  # anything printed by accident must not corrupt the protocol
    server = Server()
    log(
        "serving apple-doc %s over stdio (MCP %s; legacy %s)"
        % (__version__, MODERN_VERSIONS[0], ", ".join(LEGACY_VERSIONS))
    )
    for line in stdin:
        reply = handle_line(server, line)
        if reply is not None:
            stdout.write(encode(reply))
            stdout.flush()
    return 0
