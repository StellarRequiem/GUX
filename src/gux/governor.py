"""Governor — the public driver that wires up gates, audit chain, and
license/trial checks.

Usage:

    governor = Governor.from_yaml(
        constitution="./constitution.yaml",
        audit_path="./audit_chain.jsonl",
    )
    result = governor.dispatch(DispatchRequest(...))
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gux.audit import AuditChain
from gux.gates import GATES
from gux.license import LicenseGate
from gux.types import (
    DispatchContext,
    DispatchPendingApproval,
    DispatchRefused,
    DispatchRequest,
    DispatchResult,
    DispatchSucceeded,
    StepResult,
)


def _load_yaml_or_json(path: Path) -> dict[str, Any]:
    """Load a constitution file. Prefers PyYAML if installed; falls back to
    the stdlib json loader so the kernel runs without external deps."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        import json
        # Tolerate JSON-formatted constitution files. .yaml without yaml
        # installed is a no-go; tell the user clearly.
        if path.suffix.lower() in (".yaml", ".yml"):
            raise RuntimeError(
                f"PyYAML not installed but {path} is a YAML file. Either "
                "`pip install gux-governor[yaml]` or supply the constitution "
                "as JSON."
            )
        return json.loads(text)


# ─────────────────────────────────────────────────────────────────────────
# Built-in tool registry. Operators can extend at construction time.
# ─────────────────────────────────────────────────────────────────────────
DEFAULT_TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "memory_recall.v1": {
        "name": "memory_recall", "version": "1",
        "side_effects": "read_only",
        "required": ["query"],
    },
    "llm_think.v1": {
        "name": "llm_think", "version": "1",
        "side_effects": "read_only",
        "required": ["prompt"],
    },
    "file_read.v1": {
        "name": "file_read", "version": "1",
        "side_effects": "read_only",
        "required": ["path"],
    },
    "file_write.v1": {
        "name": "file_write", "version": "1",
        "side_effects": "filesystem",
        "required": ["path", "content"],
    },
    "mcp_call.v1": {
        "name": "mcp_call", "version": "1",
        "side_effects": "network",
        "required": ["server_name", "tool_name"],
    },
    "code_exec.v1": {
        "name": "code_exec", "version": "1",
        "side_effects": "external",
        "required": ["code"],
        "required_initiative_level": "L4",
    },
}


@dataclass
class Governor:
    """The public dispatch driver.

    Construct with `Governor.from_yaml(...)` for the common case, or
    pass dicts directly for tests / programmatic use.
    """

    constitution: dict[str, Any]
    audit: AuditChain
    registry: dict[str, dict[str, Any]] = field(default_factory=dict)
    mcp_registry: dict[str, Any] = field(default_factory=dict)
    license_gate: LicenseGate = field(default_factory=lambda: LicenseGate.load())
    _session_calls: dict[str, int] = field(default_factory=dict)
    _session_tokens: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_yaml(
        cls,
        constitution: str | Path,
        audit_path: str | Path = "./audit_chain.jsonl",
        registry: dict[str, dict[str, Any]] | None = None,
        mcp_registry: dict[str, Any] | None = None,
    ) -> "Governor":
        const = _load_yaml_or_json(Path(constitution))
        return cls(
            constitution=const,
            audit=AuditChain(path=Path(audit_path)),
            registry={**DEFAULT_TOOL_REGISTRY, **(registry or {})},
            mcp_registry=mcp_registry or {},
        )

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        """Walk all twelve gates against the given dispatch request."""
        # License / trial gate — kept outside the kernel pipeline because
        # it's commercial, not kernel-ABI.
        license_check = self.license_gate.check()
        if not license_check.ok:
            return DispatchRefused(
                trace=[],
                reason="license_invalid",
                detail=license_check.message,
            )

        agent = self._lookup_agent(request.instance_id)
        ctx = DispatchContext(
            request=request,
            agent=agent,
            constitution=self.constitution,
            registry=self.registry,
            mcp_registry=self.mcp_registry,
            session_calls=self._session_calls.get(request.session_id, 0),
            session_tokens=self._session_tokens.get(request.session_id, 0),
        )

        trace: list[tuple[str, StepResult]] = []
        t0 = time.perf_counter()
        terminal: StepResult | None = None
        for gate in GATES:
            result = gate.evaluate(ctx)
            trace.append((gate.name, result))
            if result.terminal:
                terminal = result
                break
        pipeline_ms = (time.perf_counter() - t0) * 1000.0

        # Increment counter only on GO (refused / pending don't burn a slot).
        if terminal is None:
            self._session_calls[request.session_id] = ctx.session_calls + 1

        # Append the canonical dispatch event.
        self.audit.append(
            "tool_call_dispatched",
            {
                "instance_id": request.instance_id,
                "tool_key": ctx.key,
                "session_id": request.session_id,
                "agent_dna": agent.get("dna", ""),
            },
        )

        if terminal is None:
            self.audit.append("tool_call_succeeded", {
                "instance_id": request.instance_id,
                "tool_key": ctx.key,
                "session_id": request.session_id,
                "pipeline_ms": pipeline_ms,
            })
            return DispatchSucceeded(trace=trace, pipeline_ms=pipeline_ms)

        if terminal.verdict == "PENDING":
            self.audit.append("tool_call_pending_approval", {
                "instance_id": request.instance_id,
                "tool_key": ctx.key,
                "session_id": request.session_id,
                "gate_source": terminal.gate_source or "",
            })
            return DispatchPendingApproval(
                trace=trace,
                pipeline_ms=pipeline_ms,
                gate_source=terminal.gate_source or "",
                detail=terminal.detail or "",
            )

        # REFUSE
        self.audit.append("tool_call_refused", {
            "instance_id": request.instance_id,
            "tool_key": ctx.key,
            "session_id": request.session_id,
            "reason": terminal.reason or "",
        })
        return DispatchRefused(
            trace=trace,
            pipeline_ms=pipeline_ms,
            reason=terminal.reason or "",
            detail=terminal.detail or "",
        )

    def _lookup_agent(self, instance_id: str) -> dict[str, Any]:
        """Pull the agent record from constitution['agents'][instance_id].

        If no agents block exists, fall back to a single-agent constitution
        where the top-level 'agent' field is the only agent — useful for
        prototype use.
        """
        agents = self.constitution.get("agents")
        if isinstance(agents, dict) and instance_id in agents:
            return agents[instance_id]
        # single-agent shape
        single = self.constitution.get("agent")
        if isinstance(single, dict):
            return single
        raise KeyError(
            f"instance_id {instance_id!r} not found in constitution"
        )
