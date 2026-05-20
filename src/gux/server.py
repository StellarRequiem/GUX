"""Minimal HTTP sidecar — stdlib only.

Exposes:
    GET  /healthz          → {"ok": true, ...}
    GET  /license          → current license status
    POST /v1/dispatch      → run a dispatch through the kernel
    GET  /v1/audit/tail    → last N audit chain entries
    GET  /v1/audit/verify  → re-verify chain integrity

Listen on http://127.0.0.1:7421 by default. Bind locally — the kernel
is designed to be a sidecar, not an exposed service.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

from gux.governor import Governor
from gux.license import LicenseGate
from gux.types import DispatchRequest


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7421


def _json_response(handler: BaseHTTPRequestHandler, status: int, body: Any) -> None:
    payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    # Allow the G.UX product UI (and any browser-based client) to call
    # the local sidecar from a different origin.
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    handler.end_headers()
    handler.wfile.write(payload)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if not length:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON body: {e}")


def make_handler(governor: Governor) -> type[BaseHTTPRequestHandler]:
    """Return a handler class closed over the live Governor instance."""

    class Handler(BaseHTTPRequestHandler):
        # Silence default access logs — they're noisy and the audit chain
        # is the canonical record anyway.
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            if parsed.path == "/healthz":
                _json_response(self, 200, {
                    "ok": True,
                    "service": "gux-governor",
                    "version": "0.5.0",
                    "license": governor.license_gate.check().__dict__,
                })
                return
            if parsed.path == "/license":
                check = governor.license_gate.check()
                _json_response(self, 200, {
                    "plan": governor.license_gate.plan,
                    "ok": check.ok,
                    "message": check.message,
                    "days_remaining": check.days_remaining,
                    "license_file": governor.license_gate.display_path,
                })
                return
            if parsed.path == "/v1/audit/tail":
                n = int(qs.get("n", ["50"])[0])
                lines = _tail(governor.audit.path, n)
                _json_response(self, 200, {"entries": lines})
                return
            if parsed.path == "/v1/audit/verify":
                ok, msg = governor.audit.verify()
                _json_response(self, 200, {"ok": ok, "message": msg})
                return
            _json_response(self, 404, {"error": "not found", "path": self.path})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/v1/dispatch":
                _json_response(self, 404, {"error": "not found", "path": self.path})
                return
            try:
                body = _read_json_body(self)
            except ValueError as e:
                _json_response(self, 400, {"error": str(e)})
                return
            try:
                request = DispatchRequest(
                    instance_id=body["instance_id"],
                    tool_name=body["tool_name"],
                    tool_version=str(body.get("tool_version", "1")),
                    args=body.get("args", {}),
                    session_id=body.get("session_id", ""),
                    task_caps=body.get("task_caps"),
                )
            except KeyError as e:
                _json_response(self, 400, {
                    "error": f"missing required field: {e.args[0]}",
                })
                return
            result = governor.dispatch(request)
            payload = {
                "verdict": result.kind.upper(),
                "pipeline_ms": result.pipeline_ms,
                "trace": [
                    {
                        "gate": name,
                        "verdict": step.verdict,
                        "reason": step.reason,
                        "detail": step.detail,
                        "gate_source": step.gate_source,
                    }
                    for name, step in result.trace
                ],
            }
            if result.kind == "refuse":
                payload["reason"] = result.reason  # type: ignore[attr-defined]
                payload["detail"] = result.detail  # type: ignore[attr-defined]
            elif result.kind == "pending":
                payload["gate_source"] = result.gate_source  # type: ignore[attr-defined]
                payload["detail"] = result.detail  # type: ignore[attr-defined]
            _json_response(self, 200, payload)

    return Handler


def _tail(path: Path, n: int) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        lines = [ln for ln in f if ln.strip()]
    return [json.loads(ln) for ln in lines[-n:]]


def serve(governor: Governor, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Run the sidecar in the foreground. Ctrl-C to stop."""
    handler = make_handler(governor)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"  ▸ gux-governor v0.5.0 listening on http://{host}:{port}")
    print(f"  ▸ license:  {governor.license_gate.check().message}")
    print(f"  ▸ audit:    {governor.audit.path}")
    print()
    print("  GET  /healthz")
    print("  GET  /license")
    print("  GET  /v1/audit/tail?n=50")
    print("  GET  /v1/audit/verify")
    print("  POST /v1/dispatch")
    print()
    print("  Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  ▸ shutting down…")
        server.shutdown()
