"""LQA MCP server - Streamable HTTP transport, MCP spec 2025-11-25.

Exposes the LQA localization QA engine as MCP tools so any MCP-capable client
(including Alexa+ integrations) can ask it to review a translation against a
client glossary.

Transport conformance (2025-11-25 Streamable HTTP):
  * single MCP endpoint accepting POST  (/mcp)
  * POST returns either application/json or text/event-stream
  * server assigns a session via the Mcp-Session-Id response header
  * GET opens a standalone SSE stream; DELETE terminates the session
  * Origin header is validated on every request -> 403 if not allowed
  * JSON-RPC notifications -> 202 Accepted with no body
  * unknown JSON-RPC method -> 404 with error code -32601
  * X-Accel-Buffering: no on SSE responses

Standard library only, so it runs anywhere with no install step.
"""

from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# make the sibling lqa package importable when run from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from lqa.glossary import load_glossary  # noqa: E402
from lqa.reviewer import Segment, review_document  # noqa: E402
from lqa.providers import get_provider  # noqa: E402

PROTOCOL_VERSION = "2025-11-25"
SERVER_NAME = "lqa-mcp"
SERVER_VERSION = "1.0.0"

# Sessions: id -> {"queue": Queue} for the standalone GET stream
_SESSIONS: dict[str, dict] = {}
_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# tool definitions
# --------------------------------------------------------------------------

TOOLS = [
    {
        "name": "review_translation",
        "description": (
            "Review translated segments against a client glossary and return a scored, "
            "per-segment QA report. Deterministic checks (glossary/terminology, source-language "
            "leakage, omissions, formatting, duplicated words) are authoritative. Handles "
            "Romanian inflection, so glossary 'cont curent' matches 'contului curent' while "
            "'cont' does not match 'contact'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "segments": {
                    "type": "array",
                    "description": "Segments to review.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "source": {"type": "string"},
                            "target": {"type": "string"},
                        },
                        "required": ["source", "target"],
                    },
                },
                "glossary": {
                    "type": "string",
                    "description": "CSV or TSV glossary: source,target[,note]",
                },
                "source_lang": {"type": "string", "default": "ro"},
                "target_lang": {"type": "string", "default": "en"},
            },
            "required": ["segments"],
        },
    },
    {
        "name": "check_glossary_terms",
        "description": (
            "Report which glossary terms are required by each source segment and whether each "
            "one is present in its translation. Use this when you only need terminology "
            "compliance, without a full QA review."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "source": {"type": "string"},
                            "target": {"type": "string"},
                        },
                        "required": ["source", "target"],
                    },
                },
                "glossary": {"type": "string", "description": "CSV/TSV glossary"},
                "source_lang": {"type": "string", "default": "ro"},
                "target_lang": {"type": "string", "default": "en"},
            },
            "required": ["segments", "glossary"],
        },
    },
]


def _as_segments(raw) -> list[Segment]:
    out = []
    for i, item in enumerate(raw or [], start=1):
        if not isinstance(item, dict):
            continue
        out.append(Segment(
            id=str(item.get("id", i)),
            source=str(item.get("source", "")),
            target=str(item.get("target", "")),
        ))
    return out


def _tool_review(args: dict) -> dict:
    segs = _as_segments(args.get("segments"))
    if not segs:
        return {"error": "no segments supplied"}
    glossary = load_glossary(args.get("glossary") or "") if args.get("glossary") else {}
    provider = get_provider(None if os.environ.get("NEBIUS_API_KEY") else "heuristic")
    use_model = bool(os.environ.get("NEBIUS_API_KEY"))
    report = review_document(
        provider, segs, glossary,
        source_lang=args.get("source_lang", "ro"),
        target_lang=args.get("target_lang", "en"),
        use_model=use_model,
    )
    findings = []
    for s in report.segments:
        for iss in getattr(s, "issues", []) or []:
            findings.append({
                "segment": getattr(s, "id", ""),
                "severity": getattr(iss, "severity", ""),
                "detail": getattr(iss, "detail", "") or getattr(iss, "note", ""),
                "engine": getattr(iss, "engine", ""),
            })
    return {
        "score": report.score,
        "counts": getattr(report, "counts", {}),
        "findings": findings,
        "engines": "heuristic+model" if use_model else "heuristic",
    }


def _tool_glossary(args: dict) -> dict:
    segs = _as_segments(args.get("segments"))
    glossary = load_glossary(args.get("glossary") or "")
    rows = []
    for s in segs:
        required = []
        for term, spec in glossary.items():
            if _term_in(term, s.source):
                expected = spec if isinstance(spec, str) else getattr(spec, "target", "")
                required.append({
                    "term": term,
                    "expected": expected,
                    "present": _term_in(expected, s.target),
                })
        rows.append({"segment": s.id, "required_terms": required})
    return {"segments": rows, "glossary_size": len(glossary)}


def _fold(text: str) -> str:
    t = (text or "").lower()
    for a, b in (("ă", "a"), ("â", "a"), ("î", "i"), ("ș", "s"), ("ț", "t")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-zA-Z\s]+", " ", t)).strip()


def _term_in(term: str, text: str) -> bool:
    """Inflection-aware containment: 'cont curent' matches 'contului curent',
    but 'cont' must not match 'contact'."""
    hay = " " + _fold(text) + " "
    for word in _fold(term).split():
        if len(word) <= 2:
            if not re.search(r"(^|\s)" + re.escape(word) + r"($|\s)", hay):
                return False
            continue
        stem = word[:-1]
        if not re.search(r"(^|\s)" + re.escape(stem) + r"[a-z]*($|\s)", hay):
            return False
    return True


TOOL_IMPL = {
    "review_translation": _tool_review,
    "check_glossary_terms": _tool_glossary,
}


# --------------------------------------------------------------------------
# JSON-RPC
# --------------------------------------------------------------------------

def _result(rid, payload):
    return {"jsonrpc": "2.0", "id": rid, "result": payload}


def _error(rid, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": err}


def handle_rpc(msg: dict, session: dict | None) -> dict | None:
    """Return a JSON-RPC response, or None for a notification."""
    if not isinstance(msg, dict):
        return _error(None, -32600, "Invalid Request")
    method = msg.get("method")
    rid = msg.get("id")
    is_notification = "id" not in msg

    if method == "initialize":
        return _result(rid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return _result(rid, {})
    if method == "tools/list":
        return _result(rid, {"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        impl = TOOL_IMPL.get(name)
        if impl is None:
            return _result(rid, {
                "content": [{"type": "text", "text": f"unknown tool: {name}"}],
                "isError": True,
            })
        try:
            out = impl(params.get("arguments") or {})
        except Exception as exc:  # surface tool failure to the client, do not crash
            return _result(rid, {
                "content": [{"type": "text", "text": f"tool error: {exc}"}],
                "isError": True,
            })
        return _result(rid, {
            "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
            "isError": False,
        })

    if is_notification:
        return None
    return _error(rid, -32601, f"Method not found: {method}")


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def _sse(payloads: list[dict]) -> bytes:
    out = []
    for p in payloads:
        out.append("event: message\n")
        out.append("data: " + json.dumps(p, ensure_ascii=False) + "\n\n")
    return "".join(out).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = f"{SERVER_NAME}/{SERVER_VERSION}"
    protocol_version = "HTTP/1.1"

    # -- helpers ---------------------------------------------------------
    def _allowed_origin(self) -> bool:
        """Spec: MUST validate Origin; 403 when present and not allowed."""
        origin = self.headers.get("Origin")
        if not origin:
            return True  # non-browser client (e.g. curl) - allowed
        allow = os.environ.get("LQA_ALLOWED_ORIGINS", "")
        allowed = [o.strip() for o in allow.split(",") if o.strip()]
        # localhost on any port is allowed by default for local development
        if origin in allowed:
            return True
        return bool(re.match(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$", origin))

    def _send(self, code: int, body: bytes = b"", ctype: str = "application/json",
              extra: dict | None = None):
        self.send_response(code)
        if body:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code, obj, extra=None):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json", extra)

    # -- routes ----------------------------------------------------------
    def do_OPTIONS(self):  # noqa: N802
        if not self._allowed_origin():
            return self._json(403, _error(None, -32000, "Origin not allowed"))
        self._send(204, extra={
            "Access-Control-Allow-Origin": self.headers.get("Origin", "*"),
            "Access-Control-Allow-Methods": "POST, GET, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Accept, Mcp-Session-Id, MCP-Protocol-Version",
        })

    def do_POST(self):  # noqa: N802
        if not self._allowed_origin():
            return self._json(403, _error(None, -32000, "Origin not allowed"))
        if not self.path.rstrip("/").endswith("/mcp"):
            return self._json(404, _error(None, -32601, "Not found"))

        accept = self.headers.get("Accept", "")
        if "text/event-stream" not in accept or "application/json" not in accept:
            return self._json(400, _error(
                None, -32000,
                "Accept header must include both application/json and text/event-stream"))

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            msg = json.loads(raw.decode("utf-8")) if raw else None
        except Exception:
            return self._json(400, _error(None, -32700, "Parse error"))

        # version header, when supplied, must match the body's declared version
        hdr_ver = self.headers.get("MCP-Protocol-Version")
        if hdr_ver and hdr_ver != PROTOCOL_VERSION:
            return self._json(400, _error(
                None, -32000,
                f"Unsupported protocol version: {hdr_ver}",
                {"supported": [PROTOCOL_VERSION]}))

        sess_id = self.headers.get("Mcp-Session-Id")
        session = _SESSIONS.get(sess_id) if sess_id else None

        # a batch is legal JSON-RPC; handle list or single
        msgs = msg if isinstance(msg, list) else [msg]
        responses = []
        for m in msgs:
            m = m or {}
            if isinstance(m, dict) and m.get("method") == "initialize" and not sess_id:
                new_id = uuid.uuid4().hex
                with _LOCK:
                    _SESSIONS[new_id] = {"q": queue.Queue()}
                sess_id = new_id
                session = _SESSIONS[new_id]
            r = handle_rpc(m, session)
            if r is not None:
                responses.append(r)

        extra = {"Mcp-Session-Id": sess_id} if sess_id else {}

        # notifications only -> 202 with no body
        if not responses:
            return self._send(202, b"", extra=extra)

        # spec: an unimplemented RPC method MUST return HTTP 404 carrying a
        # JSON-RPC -32601 error, so the status code agrees with the body.
        method_not_found = any(
            (r.get("error") or {}).get("code") == -32601 for r in responses
        )

        # if the client prefers a stream, answer as SSE
        if self.headers.get("Accept", "").find("text/event-stream") == 0:
            return self._send(404 if method_not_found else 200,
                              _sse(responses), "text/event-stream",
                              {**extra, "X-Accel-Buffering": "no", "Cache-Control": "no-cache"})
        return self._json(404 if method_not_found else 200,
                          responses[0] if len(responses) == 1 else responses, extra)

    def do_GET(self):  # noqa: N802
        """Standalone SSE stream (2025-11-25 revision)."""
        if not self._allowed_origin():
            return self._json(403, _error(None, -32000, "Origin not allowed"))
        sess_id = self.headers.get("Mcp-Session-Id")
        session = _SESSIONS.get(sess_id) if sess_id else None
        if not session:
            return self._json(400, _error(None, -32000, "Missing or unknown Mcp-Session-Id"))

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Mcp-Session-Id", sess_id)
        self.end_headers()
        self.wfile.write(b": connected\r\n\r\n")
        self.wfile.flush()
        try:
            while True:
                try:
                    item = session["q"].get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keep-alive\r\n\r\n")  # SSE comment
                    self.wfile.flush()
                    continue
                if item is None:
                    break
                self.wfile.write(_sse([item]))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_DELETE(self):  # noqa: N802
        if not self._allowed_origin():
            return self._json(403, _error(None, -32000, "Origin not allowed"))
        sess_id = self.headers.get("Mcp-Session-Id")
        if sess_id:
            s = _SESSIONS.pop(sess_id, None)
            if s:
                try:
                    s["q"].put_nowait(None)
                except Exception:
                    pass
        self._send(204)

    def log_message(self, fmt, *args):  # quieter, structured
        sys.stderr.write("[lqa-mcp] %s\n" % (fmt % args))


def main():
    host = os.environ.get("LQA_HOST", "127.0.0.1")   # spec: SHOULD bind localhost
    port = int(os.environ.get("LQA_PORT", "8765"))
    srv = ThreadingHTTPServer((host, port), Handler)
    sys.stderr.write(f"[lqa-mcp] Streamable HTTP on http://{host}:{port}/mcp "
                     f"(spec {PROTOCOL_VERSION})\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
