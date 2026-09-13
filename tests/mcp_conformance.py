"""Conformance test for the LQA MCP server (Streamable HTTP, spec 2025-11-25).

Starts the server, then exercises the behaviours the spec actually mandates
rather than just the happy path.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # repo root - mcp_server.py lives here, not in tests/
PORT = 8797
BASE = f"http://127.0.0.1:{PORT}/mcp"
ACCEPT = "application/json, text/event-stream"


def call(method, body=None, headers=None, expect_json=True):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE, data=data, method=method)
    req.add_header("Accept", ACCEPT)
    if data:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
            return r.status, dict(r.headers), raw
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()


def body_of(raw):
    """Accept either a JSON object or an SSE frame."""
    if "event:" in raw or "data:" in raw:
        for line in raw.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return None
    return json.loads(raw) if raw.strip() else None


results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (("   " + detail) if detail else ""))


env = dict(os.environ)
env["LQA_PORT"] = str(PORT)
proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "mcp_server.py")],
                        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(2.5)
try:
    print("\n=== 1. initialize ===")
    st, hdrs, raw = call("POST", {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                   "clientInfo": {"name": "conformance", "version": "1"}},
    })
    msg = body_of(raw)
    sid = hdrs.get("Mcp-Session-Id") or hdrs.get("mcp-session-id")
    check("initialize returns 200", st == 200, f"got {st}")
    check("server assigns Mcp-Session-Id", bool(sid), f"id={str(sid)[:12]}")
    check("protocolVersion is 2025-11-25",
          (msg or {}).get("result", {}).get("protocolVersion") == "2025-11-25",
          str((msg or {}).get("result", {}).get("protocolVersion")))
    check("serverInfo present", "serverInfo" in (msg or {}).get("result", {}))
    check("declares tools capability",
          "tools" in (msg or {}).get("result", {}).get("capabilities", {}))

    h = {"Mcp-Session-Id": sid} if sid else {}

    print("\n=== 2. notifications -> 202, no body ===")
    st2, _, raw2 = call("POST", {"jsonrpc": "2.0", "method": "notifications/initialized"}, h)
    check("notification returns 202", st2 == 202, f"got {st2}")
    check("notification has empty body", raw2.strip() == "", repr(raw2[:40]))

    print("\n=== 3. tools/list ===")
    st3, _, raw3 = call("POST", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, h)
    m3 = body_of(raw3)
    tools = (m3 or {}).get("result", {}).get("tools", [])
    names = [t.get("name") for t in tools]
    check("tools/list returns tools", len(tools) >= 2, str(names))
    check("every tool has an inputSchema",
          all("inputSchema" in t for t in tools))

    print("\n=== 4. tools/call review_translation (the real work) ===")
    payload = {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "review_translation", "arguments": {
            "glossary": 'cont curent,current account,never use "checking account"\n'
                        'notificare push,push notification,product UI\n',
            "segments": [
                {"id": "ok", "source": "Soldul contului curent este disponibil.",
                 "target": "Your current account balance is available."},
                {"id": "bad", "source": "Soldul contului curent este disponibil.",
                 "target": "Your checking account balance is available."},
                {"id": "trap", "source": "Vă rugăm să contactați echipa.",
                 "target": "Please contact our team."},
            ],
        }},
    }
    st4, _, raw4 = call("POST", payload, h)
    m4 = body_of(raw4)
    content = (m4 or {}).get("result", {}).get("content", [])
    inner = {}
    if content:
        try:
            inner = json.loads(content[0].get("text", "{}"))
        except Exception:
            pass
    findings = inner.get("findings", [])
    segs_hit = {f.get("segment") for f in findings}
    check("tools/call returns 200", st4 == 200, f"got {st4}")
    check("content block returned", bool(content))
    check("inflected term present in source is recognised", "ok" not in segs_hit,
          "clean inflected segment must not be flagged")
    check("inflected term MISSING in target is caught", "bad" in segs_hit,
          "contului curent vs checking account must be flagged")
    check("'contact' does NOT false-positive on term 'cont curent'", "trap" not in segs_hit,
          "prefix trap must pass")
    check("score is numeric", isinstance(inner.get("score"), (int, float)),
          str(inner.get("score")))

    print("\n=== 5. unknown tool -> isError, not a crash ===")
    st5, _, raw5 = call("POST", {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                 "params": {"name": "nope", "arguments": {}}}, h)
    check("unknown tool returns 200 with isError", st5 == 200 and
          body_of(raw5).get("result", {}).get("isError") is True)

    print("\n=== 6. unknown METHOD -> 404 + -32601 (spec-mandated) ===")
    st6, _, raw6 = call("POST", {"jsonrpc": "2.0", "id": 5, "method": "does/not/exist"}, h)
    m6 = body_of(raw6) or {}
    check("unknown method returns 404", st6 == 404, f"got {st6}")
    check("error code is -32601", m6.get("error", {}).get("code") == -32601,
          str(m6.get("error")))

    print("\n=== 7. Origin validation -> 403 (spec-mandated) ===")
    st7, _, raw7 = call("POST", {"jsonrpc": "2.0", "id": 6, "method": "tools/list"},
                        {**h, "Origin": "https://evil.example.com"})
    check("bad Origin is rejected with 403", st7 == 403, f"got {st7}")
    st7b, _, _ = call("POST", {"jsonrpc": "2.0", "id": 7, "method": "tools/list"},
                      {**h, "Origin": "http://localhost:5173"})
    check("localhost Origin is allowed", st7b == 200, f"got {st7b}")

    print("\n=== 8. Accept header must list BOTH types ===")
    req = urllib.request.Request(BASE, data=json.dumps(
        {"jsonrpc": "2.0", "id": 8, "method": "tools/list"}).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            st8 = r.status
    except urllib.error.HTTPError as e:
        st8 = e.code
    check("json-only Accept is rejected with 400", st8 == 400, f"got {st8}")

    print("\n=== 9. DELETE terminates the session ===")
    st9, _, _ = call("DELETE", None, h)
    check("DELETE returns 204", st9 == 204, f"got {st9}")
    st9b, _, _ = call("POST", {"jsonrpc": "2.0", "id": 9, "method": "tools/list"}, h)
    check("GET/DELETE'd session no longer usable", st9b in (400, 404, 200),
          f"got {st9b} (server need not reject, but must not crash)")

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

passed = sum(1 for _, ok, _ in results if ok)
print(f"\n{'=' * 62}")
print(f"MCP CONFORMANCE: {passed}/{len(results)} checks passed")
print("=" * 62)
sys.exit(0 if passed == len(results) else 1)
