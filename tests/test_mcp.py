"""The MCP server, in-process and as a subprocess, against the fake asset."""

import json
import subprocess
import sys

import jsonschema
import pytest

from apple_doc.mcp import LEGACY_VERSIONS, MODERN_VERSIONS, TOOLS, Server, encode, handle_line

CLIENT = {"name": "test", "version": "1"}

MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


def req(id_, method, params=None):
    msg = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def call(server, msg):
    return handle_line(server, json.dumps(msg).encode())


@pytest.fixture
def env(built, monkeypatch):
    for k in ("APPLE_DOC_ASSET_GLOB", "APPLE_DOC_INDEX"):
        monkeypatch.setenv(k, built.env[k])
    return built


@pytest.fixture
def legacy(env):
    s = Server()
    r = call(
        s,
        req(
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "1"},
            },
        ),
    )
    assert r["result"]["protocolVersion"] == "2025-06-18"
    assert call(s, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    return s


def tool(server, name, args, modern=False):
    params = {"name": name, "arguments": args}
    if modern:
        params["_meta"] = MODERN_META
    return call(server, req(9, "tools/call", params))["result"]


def test_tool_schemas_are_valid_json_schema():
    names = [t["name"] for t in TOOLS]
    assert names == ["search_apple_docs", "read_apple_doc", "list_frameworks"]
    for t in TOOLS:
        jsonschema.Draft202012Validator.check_schema(t["inputSchema"])
        assert t["inputSchema"]["type"] == "object" and t["description"]
    v = jsonschema.Draft202012Validator(TOOLS[0]["inputSchema"])
    assert v.is_valid({"query": "NSView", "framework": "AppKit", "limit": 3})
    assert not v.is_valid({"query": "NSView", "limit": 11})
    assert not v.is_valid({})


def test_initialize_negotiates_legacy_versions(env):
    for asked, got in (
        ("2025-11-25", "2025-11-25"),
        ("2024-11-05", "2024-11-05"),
        ("1999-01-01", LEGACY_VERSIONS[0]),
        ("2026-07-28", LEGACY_VERSIONS[0]),
    ):
        r = call(
            Server(),
            req(
                1,
                "initialize",
                {"protocolVersion": asked, "capabilities": {}, "clientInfo": CLIENT},
            ),
        )
        res = r["result"]
        assert res["protocolVersion"] == got
        assert res["capabilities"] == {"tools": {"listChanged": False}}
        assert res["serverInfo"]["name"] == "apple-doc" and "entity" not in res["instructions"]


def test_legacy_list_and_call(legacy):
    r = call(legacy, req(2, "tools/list"))
    assert [t["name"] for t in r["result"]["tools"]][0] == "search_apple_docs"
    res = tool(legacy, "search_apple_docs", {"query": "noResponderFor beep", "limit": 1})
    assert res["isError"] is False
    text = res["content"][0]["text"]
    assert text.startswith("1. noResponder(for:)") and "beeps" in text


def test_modern_requests_need_no_handshake(env):
    s = Server()
    d = call(s, req("d", "server/discover", {"_meta": MODERN_META}))["result"]
    assert d["supportedVersions"][0] == MODERN_VERSIONS[0] and "tools" in d["capabilities"]
    assert d["resultType"] == "complete"
    r = call(s, req(2, "tools/list", {"_meta": MODERN_META}))["result"]
    assert r["resultType"] == "complete" and len(r["tools"]) == 3
    assert r["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "apple-doc"
    res = tool(s, "read_apple_doc", {"path": "/documentation/AppKit/NSQuokkaView"}, modern=True)
    assert res["isError"] is False and "#Overview" in res["content"][0]["text"]


def test_modern_version_and_meta_errors(env):
    s = Server()
    bad = dict(MODERN_META, **{"io.modelcontextprotocol/protocolVersion": "1900-01-01"})
    e = call(s, req(1, "tools/list", {"_meta": bad}))["error"]
    assert e["code"] == -32022 and e["data"]["requested"] == "1900-01-01"
    assert e["data"]["supported"] == MODERN_VERSIONS
    legacy_meta = dict(MODERN_META, **{"io.modelcontextprotocol/protocolVersion": "2025-06-18"})
    e = call(s, req(4, "tools/list", {"_meta": legacy_meta}))["error"]
    assert e["code"] == -32022 and "initialize" in e["message"]
    no_caps = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}
    assert call(s, req(2, "tools/list", {"_meta": no_caps}))["error"]["code"] == -32602
    e = call(s, req(3, "tools/list"))["error"]  # neither modern _meta nor initialize
    assert e["code"] == -32602 and "initialize" in e["message"]


def test_read_section_and_frameworks(legacy):
    page = tool(legacy, "read_apple_doc", {"path": "NSQuokkaView"})["content"][0]["text"]
    assert "read_apple_doc(path='/documentation/AppKit/NSQuokkaView', section=ANCHOR)" in page
    assert "apple-doc --full" not in page
    hit = tool(legacy, "search_apple_docs", {"query": "glimmerKey"})["content"][0]["text"]
    assert hit.endswith("full page: read_apple_doc(path))")
    res = tool(legacy, "read_apple_doc", {"path": "NSQuokkaView", "section": "Overview"})
    assert res["content"][0]["text"].startswith("## Overview")
    res = tool(legacy, "list_frameworks", {})
    assert res["content"][0]["text"].splitlines()[0].startswith("AppKit (")


def test_tool_errors_are_results_not_crashes(legacy):
    cases = [
        ("search_apple_docs", {"query": "x", "framework": "HIG"}, "list_frameworks shows all"),
        ("search_apple_docs", {"query": "x", "limit": 50}, "between 1 and 10"),
        ("search_apple_docs", {"query": "x", "limit": True}, "must be an integer"),
        ("search_apple_docs", {"query": "x", "limit": "3"}, "must be an integer"),
        ("search_apple_docs", {"query": "x" * 3000}, "too long"),
        ("search_apple_docs", {"query": "x", "framework": ""}, "'framework' needs a name"),
        ("search_apple_docs", {"query": ""}, "'query' is required"),
        ("search_apple_docs", {"query": "the of"}, "no searchable words"),
        ("search_apple_docs", {"query": "x", "bogus": 1}, "unknown argument(s): bogus"),
        ("read_apple_doc", {"path": "/documentation/AppKit/Nope"}, "no page"),
        ("read_apple_doc", {"path": "NSQuokkaView", "section": "Nope"}, "its sections"),
        ("read_apple_doc", {}, "'path' is required"),
    ]
    for name, args, needle in cases:
        res = tool(legacy, name, args)
        assert res["isError"] is True, (name, args)
        assert needle in res["content"][0]["text"], (name, args, res)
    res = tool(legacy, "search_apple_docs", {"query": "qwxzzy"})
    assert res["isError"] is False and "No hits" in res["content"][0]["text"]


def test_index_missing_and_stale_are_explained(tool, monkeypatch):
    for k in ("APPLE_DOC_ASSET_GLOB", "APPLE_DOC_INDEX"):
        monkeypatch.setenv(k, tool.env[k])
    s = Server()
    call(
        s,
        req(
            1,
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": CLIENT},
        ),
    )
    res = call(
        s, req(2, "tools/call", {"name": "search_apple_docs", "arguments": {"query": "beep"}})
    )["result"]
    assert res["isError"] is True and "apple-doc --build" in res["content"][0]["text"]
    assert tool("--build").returncode == 0
    import os

    st = os.stat(tool.asset)
    os.utime(tool.asset, (st.st_atime, st.st_mtime + 50))
    res = call(
        s,
        req(
            3, "tools/call", {"name": "search_apple_docs", "arguments": {"query": "noResponderFor"}}
        ),
    )["result"]
    assert res["isError"] is False and "apple-doc --build" in res["content"][0]["text"]


def test_protocol_errors(legacy):
    assert call(legacy, req(5, "resources/list"))["error"]["code"] == -32601
    assert call(legacy, req(5, "tools/call", {"name": "nope"}))["error"]["code"] == -32602
    e = call(legacy, req(5, "tools/call", {"name": "list_frameworks", "arguments": [1]}))
    assert e["error"]["code"] == -32602
    assert handle_line(legacy, b"{not json")["error"]["code"] == -32700
    assert handle_line(legacy, b"\xff\xfe")["error"]["code"] == -32700
    assert handle_line(legacy, b"[1, 2]")["error"]["code"] == -32600
    assert (
        handle_line(legacy, b'{"jsonrpc": "1.0", "id": 1, "method": "ping"}')["error"]["code"]
        == -32600
    )
    assert (
        handle_line(legacy, b'{"jsonrpc": "2.0", "id": null, "method": "ping"}')["error"]["code"]
        == -32600
    )
    assert handle_line(legacy, b'{"jsonrpc":"2.0","id":7,"result":{}}') is None
    assert handle_line(legacy, b"   ") is None
    assert call(legacy, req(6, "ping"))["result"] == {}
    assert call(legacy, req(7, "tools/call", {}))["error"]["message"] == "tools/call needs 'name'"
    both = b'{"jsonrpc":"2.0","id":8,"method":"ping","result":{}}'
    assert handle_line(legacy, both)["error"]["code"] == -32600
    ok = tool(legacy, "search_apple_docs", {"query": "glimmerKey", "limit": 2.0})
    assert ok["isError"] is False


def test_encoded_messages_are_single_lines():
    line = encode({"jsonrpc": "2.0", "id": 1, "result": {"text": "a\nb c"}})
    assert line.count("\n") == 1 and line.endswith("\n")
    assert len(line.splitlines()) == 1 and json.loads(line)["result"]["text"] == "a\nb\u2028c"


def test_subprocess_session(built):
    msgs = [
        req(
            1,
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "script", "version": "1"},
            },
        ),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        req(2, "tools/list"),
        req(
            3,
            "tools/call",
            {
                "name": "search_apple_docs",
                "arguments": {"query": "glimmerKey", "framework": "AppKit"},
            },
        ),
        req(
            4,
            "tools/call",
            {"name": "read_apple_doc", "arguments": {"path": "/documentation/AppKit/LongWidget"}},
        ),
        req(5, "tools/call", {"name": "list_frameworks", "arguments": {}}),
        req(6, "tools/call", {"name": "read_apple_doc", "arguments": {"path": "nope"}}),
        req(7, "no/such/method"),
        req("s", "server/discover", {"_meta": MODERN_META}),
    ]
    stdin = "".join(json.dumps(m) + "\n" for m in msgs) + "{oops\n"
    r = subprocess.run(
        [sys.executable, "-m", "apple_doc", "--mcp"],
        input=stdin,
        env=built.env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    replies = [json.loads(ln) for ln in lines]  # every stdout line is a protocol message
    assert [m.get("id") for m in replies] == [1, 2, 3, 4, 5, 6, 7, "s", None]
    by_id = {m.get("id"): m for m in replies}
    assert "glimmerKey()" in by_id[3]["result"]["content"][0]["text"]
    long = by_id[4]["result"]["content"][0]["text"].splitlines()
    assert "... (41 more lines)" in long
    assert by_id[6]["result"]["isError"] is True
    assert by_id[7]["error"]["code"] == -32601
    assert by_id[None]["error"]["code"] == -32700
    assert "serving apple-doc" in r.stderr and "Traceback" not in r.stderr


def test_mcp_flag_conflicts(built):
    assert built("--mcp", "query").returncode == 2
    assert built("--mcp", "--json").returncode == 2
    assert built("--mcp", "--build").returncode == 2


def test_discover_and_ping_validate_modern_meta(env):
    s = Server()
    bad = dict(MODERN_META, **{"io.modelcontextprotocol/protocolVersion": "1900-01-01"})
    for method in ("server/discover", "ping"):
        e = call(s, req(1, method, {"_meta": bad}))["error"]
        assert e["code"] == -32022 and e["data"]["requested"] == "1900-01-01"
        no_caps = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}
        assert call(s, req(2, method, {"_meta": no_caps}))["error"]["code"] == -32602
        ok = call(s, req(3, method, {"_meta": MODERN_META}))["result"]
        assert ok["resultType"] == "complete"
    assert call(s, req(4, "server/discover"))["error"]["code"] == -32602
    assert call(s, req(5, "ping"))["result"] == {}  # legacy ping, even before initialize


def test_malformed_messages_never_stop_the_server(built):
    nested = "[" * 100000 + "]" * 100000
    bad_lines = [
        '{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":NaN}}',
        '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":'
        '{"io.modelcontextprotocol/protocolVersion":Infinity}}}',
        '{"jsonrpc":"2.0","id":"\\udc80","method":"ping"}',
        '{"jsonrpc":"2.0","id":"x","method":"tools/call","params":{"name":"search_apple_docs",'
        '"arguments":{"query":"\\ud800 glimmerKey"}}}',
        '{"jsonrpc":"2.0","id":2,"method":"ping","params":' + nested + "}",
        nested,
        '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search_apple_docs",'
        '"arguments":{"query":' + nested + "}}}",
        "\ud800 garbage",
    ]
    stdin = ""
    for i, bad in enumerate(bad_lines):
        stdin += bad + "\n" + json.dumps(req("ok%d" % i, "ping")) + "\n"
    r = subprocess.run(
        [sys.executable, "-m", "apple_doc", "--mcp"],
        input=stdin.encode("utf-8", "surrogatepass"),
        env=built.env,
        capture_output=True,
        timeout=60,
    )
    assert r.returncode == 0
    assert b"Traceback" not in r.stderr
    out = r.stdout.decode("utf-8")  # strictly valid UTF-8
    replies = [json.loads(ln) for ln in out.splitlines()]
    assert all(ln.isascii() for ln in out.splitlines())
    ids = [m.get("id") for m in replies]
    for i in range(len(bad_lines)):
        assert "ok%d" % i in ids, (i, ids)


def test_round2_validation(env):
    s = Server()
    e = call(s, req(1, "initialize"))["error"]
    assert e["code"] == -32602 and "protocolVersion" in e["message"]
    e = call(s, req(2, "initialize", {"protocolVersion": "2025-11-25", "capabilities": []}))
    assert e["error"]["code"] == -32602
    assert call(s, req(3, "tools/list"))["error"]["code"] == -32602  # still no session
    for bad in (
        {"protocolVersion": "2025-11-25", "clientInfo": CLIENT},
        {"protocolVersion": "2025-11-25", "capabilities": {}},
        {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": 1}},
    ):
        assert call(s, req(3, "initialize", bad))["error"]["code"] == -32602
    ok = call(
        s,
        req(
            4,
            "initialize",
            {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": CLIENT},
        ),
    )
    assert ok["result"]["protocolVersion"] == "2025-11-25"
    for args in ({"query": "x", "limit": None}, {"query": "x", "framework": None}, {"query": None}):
        res = tool(s, "search_apple_docs", args)
        assert res["isError"] is True, args


def test_overflowing_version_keeps_the_request_id(built):
    line = (
        '{"jsonrpc":"2.0","id":"overflow","method":"tools/list","params":{"_meta":'
        '{"io.modelcontextprotocol/protocolVersion":1e400,'
        '"io.modelcontextprotocol/clientCapabilities":{}}}}\n'
    )
    r = subprocess.run(
        [sys.executable, "-m", "apple_doc", "--mcp"],
        input=line,
        env=built.env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    reply = json.loads(r.stdout.splitlines()[0])
    assert reply["id"] == "overflow" and reply["error"]["code"] == -32022


def test_arguments_may_be_omitted_but_not_null(legacy):
    ok = call(legacy, req(1, "tools/call", {"name": "list_frameworks"}))
    assert ok["result"]["isError"] is False
    e = call(legacy, req(2, "tools/call", {"name": "list_frameworks", "arguments": None}))
    assert e["error"]["code"] == -32602
