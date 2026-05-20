"""Layer 2 — sidecar HTTP integration tests.

Spins up the stdlib HTTP server in a background thread on an ephemeral
port, hits each endpoint with stdlib urllib.request (matches the
package's stdlib-only spirit), validates response shape + side effects
on the audit chain.

The server is per-test (fresh state each time) via the `server` fixture.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib import error, request

import pytest

from gux.audit import AuditChain
from gux.governor import DEFAULT_TOOL_REGISTRY, Governor
from gux.license import LicenseGate
from gux.server import make_handler


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


def _free_port() -> int:
    """Grab an ephemeral port the OS assigned us. Avoids collisions
    with a real gux serve the operator may have running."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def constitution() -> dict:
    """Minimal multi-agent constitution shaped for the test cases."""
    return {
        "policies": {"max_calls_per_session": 200},
        "agents": {
            "agent-green-research": {
                "role": "test_author",
                "genre": "research",
                "initiative": "L3",
                "posture": "green",
                "provider": "ollama",
                "hardware_bound": False,
                "constitution_tools": [
                    "memory_recall.v1",
                    "file_read.v1",
                    "file_write.v1",
                ],
                "dna": "deadbeefcafe",
            },
            "agent-yellow": {
                "role": "test_author",
                "genre": "operations",
                "initiative": "L2",
                "posture": "yellow",
                "provider": "ollama",
                "hardware_bound": False,
                "constitution_tools": ["memory_recall.v1", "file_write.v1"],
                "dna": "1234567890ab",
            },
            "agent-red": {
                "role": "test_author",
                "genre": "operations",
                "initiative": "L2",
                "posture": "red",
                "provider": "ollama",
                "hardware_bound": False,
                "constitution_tools": ["memory_recall.v1", "file_write.v1"],
                "dna": "ffffffffffff",
            },
        },
    }


@pytest.fixture
def hobby_license() -> LicenseGate:
    """Bypass the license disk path — always-ok hobby license so tests
    don't depend on operator's real license state."""
    return LicenseGate(
        plan="hobby",
        key="gux_hobby_TESTONLY12345678",
        activated_at=time.time(),
    )


@pytest.fixture
def audit_path(tmp_path) -> Path:
    return tmp_path / "test_audit_chain.jsonl"


@pytest.fixture
def governor(constitution, hobby_license, audit_path) -> Governor:
    return Governor(
        constitution=constitution,
        audit=AuditChain(path=audit_path),
        registry=dict(DEFAULT_TOOL_REGISTRY),
        license_gate=hobby_license,
    )


@pytest.fixture
def server(governor):
    """Spin up the server on an ephemeral port. Tears down cleanly."""
    port = _free_port()
    handler = make_handler(governor)
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    time.sleep(0.05)  # brief settle for socket bind
    yield base_url, governor
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=2)


# ─────────────────────────────────────────────────────────────────────────
# HTTP helpers — stdlib urllib matches the package's zero-deps spirit
# ─────────────────────────────────────────────────────────────────────────


def _get(url: str, timeout: float = 3.0) -> tuple[int, dict]:
    try:
        with request.urlopen(url, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _post(url: str, body: dict, timeout: float = 3.0) -> tuple[int, dict]:
    payload = json.dumps(body).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _post_raw(url: str, raw_body: bytes) -> tuple[int, dict]:
    req = request.Request(
        url,
        data=raw_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=3.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _options(url: str) -> int:
    req = request.Request(url, method="OPTIONS")
    try:
        with request.urlopen(req, timeout=3.0) as resp:
            return resp.status
    except error.HTTPError as e:
        return e.code


# ─────────────────────────────────────────────────────────────────────────
# /healthz + /license
# ─────────────────────────────────────────────────────────────────────────


class TestHealthz:
    def test_returns_200_with_ok_true(self, server):
        base, _ = server
        status, body = _get(f"{base}/healthz")
        assert status == 200
        assert body["ok"] is True
        assert body["service"] == "gux-governor"

    def test_includes_version(self, server):
        base, _ = server
        _, body = _get(f"{base}/healthz")
        assert "version" in body

    def test_includes_license_snapshot(self, server):
        base, _ = server
        _, body = _get(f"{base}/healthz")
        assert body["license"]["ok"] is True
        assert body["license"]["plan"] == "hobby"


class TestLicenseEndpoint:
    def test_returns_plan_and_status(self, server):
        base, _ = server
        status, body = _get(f"{base}/license")
        assert status == 200
        assert body["plan"] == "hobby"
        assert body["ok"] is True


# ─────────────────────────────────────────────────────────────────────────
# POST /v1/dispatch — verdict paths
# ─────────────────────────────────────────────────────────────────────────


class TestDispatchGo:
    def test_green_agent_read_only_tool_returns_go(self, server):
        base, _ = server
        status, body = _post(
            f"{base}/v1/dispatch",
            {
                "instance_id": "agent-green-research",
                "tool_name": "memory_recall",
                "args": {"query": "test"},
                "session_id": "sess-1",
            },
        )
        assert status == 200
        assert body["verdict"] == "GO"
        assert "pipeline_ms" in body

    def test_go_response_includes_full_trace(self, server):
        """GO traces ALL 12 gates."""
        base, _ = server
        _, body = _post(
            f"{base}/v1/dispatch",
            {
                "instance_id": "agent-green-research",
                "tool_name": "memory_recall",
                "args": {"query": "test"},
                "session_id": "sess-1",
            },
        )
        assert len(body["trace"]) == 12
        for step in body["trace"]:
            assert step["verdict"] == "GO"


class TestDispatchRefuse:
    def test_unknown_tool_returns_refuse(self, server):
        base, _ = server
        _, body = _post(
            f"{base}/v1/dispatch",
            {
                "instance_id": "agent-green-research",
                "tool_name": "does_not_exist",
                "session_id": "sess-1",
            },
        )
        assert body["verdict"] == "REFUSE"
        assert body["reason"] == "unknown_tool"

    def test_tool_not_in_constitution_returns_refuse(self, server):
        base, _ = server
        _, body = _post(
            f"{base}/v1/dispatch",
            {
                "instance_id": "agent-green-research",
                "tool_name": "code_exec",
                "args": {"code": "print('hi')"},
                "session_id": "sess-1",
            },
        )
        assert body["verdict"] == "REFUSE"
        assert body["reason"] == "tool_not_in_constitution"

    def test_red_posture_non_readonly_refuses(self, server):
        base, _ = server
        _, body = _post(
            f"{base}/v1/dispatch",
            {
                "instance_id": "agent-red",
                "tool_name": "file_write",
                "args": {"path": "/tmp/x", "content": "y"},
                "session_id": "sess-1",
            },
        )
        assert body["verdict"] == "REFUSE"
        assert body["reason"] == "posture_red_refuses_writes"

    def test_refuse_response_includes_trace_up_to_failure(self, server):
        """ToolLookup is gate 3; trace must end with the REFUSE step."""
        base, _ = server
        _, body = _post(
            f"{base}/v1/dispatch",
            {
                "instance_id": "agent-green-research",
                "tool_name": "does_not_exist",
                "session_id": "sess-1",
            },
        )
        assert len(body["trace"]) == 3
        assert body["trace"][-1]["verdict"] == "REFUSE"
        assert body["trace"][-1]["gate"] == "ToolLookup"


class TestDispatchPending:
    def test_yellow_posture_non_readonly_pending(self, server):
        base, _ = server
        _, body = _post(
            f"{base}/v1/dispatch",
            {
                "instance_id": "agent-yellow",
                "tool_name": "file_write",
                "args": {"path": "/tmp/x", "content": "y"},
                "session_id": "sess-1",
            },
        )
        assert body["verdict"] == "PENDING"
        assert body["gate_source"] == "posture"


# ─────────────────────────────────────────────────────────────────────────
# Request validation
# ─────────────────────────────────────────────────────────────────────────


class TestRequestValidation:
    def test_missing_instance_id_returns_400(self, server):
        base, _ = server
        status, body = _post(
            f"{base}/v1/dispatch",
            {"tool_name": "memory_recall"},
        )
        assert status == 400
        assert "instance_id" in body["error"]

    def test_missing_tool_name_returns_400(self, server):
        base, _ = server
        status, _ = _post(
            f"{base}/v1/dispatch",
            {"instance_id": "agent-green-research"},
        )
        assert status == 400

    def test_invalid_json_returns_400(self, server):
        base, _ = server
        status, body = _post_raw(
            f"{base}/v1/dispatch",
            b"not valid {[]} json",
        )
        assert status == 400
        assert "invalid JSON" in body["error"]


# ─────────────────────────────────────────────────────────────────────────
# Routing + CORS
# ─────────────────────────────────────────────────────────────────────────


class TestRouting:
    def test_unknown_get_path_returns_404(self, server):
        base, _ = server
        status, _ = _get(f"{base}/does/not/exist")
        assert status == 404

    def test_unknown_post_path_returns_404(self, server):
        base, _ = server
        status, _ = _post(f"{base}/v1/wrong", {})
        assert status == 404


class TestCorsPreflight:
    def test_options_returns_204(self, server):
        base, _ = server
        assert _options(f"{base}/v1/dispatch") == 204


# ─────────────────────────────────────────────────────────────────────────
# Audit chain integration
# ─────────────────────────────────────────────────────────────────────────


class TestAuditChain:
    def test_audit_tail_after_go_dispatch(self, server):
        """GO writes tool_call_dispatched + tool_call_succeeded."""
        base, _ = server
        _post(
            f"{base}/v1/dispatch",
            {
                "instance_id": "agent-green-research",
                "tool_name": "memory_recall",
                "args": {"query": "test"},
                "session_id": "sess-audit-1",
            },
        )
        status, body = _get(f"{base}/v1/audit/tail?n=10")
        assert status == 200
        types = [e["event_type"] for e in body["entries"]]
        assert "tool_call_dispatched" in types
        assert "tool_call_succeeded" in types

    def test_audit_tail_after_refuse_dispatch(self, server):
        """REFUSE writes tool_call_dispatched + tool_call_refused."""
        base, _ = server
        _post(
            f"{base}/v1/dispatch",
            {
                "instance_id": "agent-red",
                "tool_name": "file_write",
                "args": {"path": "/tmp/x", "content": "y"},
                "session_id": "sess-audit-2",
            },
        )
        _, body = _get(f"{base}/v1/audit/tail?n=10")
        types = [e["event_type"] for e in body["entries"]]
        assert "tool_call_refused" in types

    def test_audit_tail_after_pending_dispatch(self, server):
        """PENDING writes tool_call_dispatched + tool_call_pending_approval."""
        base, _ = server
        _post(
            f"{base}/v1/dispatch",
            {
                "instance_id": "agent-yellow",
                "tool_name": "file_write",
                "args": {"path": "/tmp/x", "content": "y"},
                "session_id": "sess-audit-3",
            },
        )
        _, body = _get(f"{base}/v1/audit/tail?n=10")
        types = [e["event_type"] for e in body["entries"]]
        assert "tool_call_pending_approval" in types

    def test_audit_verify_passes_after_dispatches(self, server):
        base, _ = server
        for i in range(3):
            _post(
                f"{base}/v1/dispatch",
                {
                    "instance_id": "agent-green-research",
                    "tool_name": "memory_recall",
                    "args": {"query": f"q{i}"},
                    "session_id": f"sess-verify-{i}",
                },
            )
        status, body = _get(f"{base}/v1/audit/verify")
        assert status == 200
        assert body["ok"] is True

    def test_audit_entries_have_chain_fields(self, server):
        base, _ = server
        _post(
            f"{base}/v1/dispatch",
            {
                "instance_id": "agent-green-research",
                "tool_name": "memory_recall",
                "args": {"query": "test"},
                "session_id": "sess-chain",
            },
        )
        _, body = _get(f"{base}/v1/audit/tail?n=5")
        for entry in body["entries"]:
            assert "seq" in entry
            assert "prev_hash" in entry
            assert "entry_hash" in entry
            assert "timestamp" in entry


# ─────────────────────────────────────────────────────────────────────────
# Session call counter integration — only GO bumps the counter
# ─────────────────────────────────────────────────────────────────────────


class TestSessionCallCounter:
    def test_call_counter_only_increments_on_go(self, server):
        """3 GO + 2 REFUSE → counter at 3."""
        base, governor = server
        sess = "sess-counter-test"
        for i in range(3):
            _post(
                f"{base}/v1/dispatch",
                {
                    "instance_id": "agent-green-research",
                    "tool_name": "memory_recall",
                    "args": {"query": f"q{i}"},
                    "session_id": sess,
                },
            )
        for i in range(2):
            _post(
                f"{base}/v1/dispatch",
                {
                    "instance_id": "agent-green-research",
                    "tool_name": "does_not_exist",
                    "session_id": sess,
                },
            )
        assert governor._session_calls[sess] == 3
