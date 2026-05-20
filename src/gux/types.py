"""Public dataclasses for G.UX dispatch + verdicts.

Mirrors the kernel ABI from forest_soul_forge/tools/dispatcher.py — the
shape downstream code switches on. Adding fields is non-breaking; renaming
or removing fields is a breaking change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


# ─────────────────────────────────────────────────────────────────────────
# DispatchRequest — what the caller passes in.
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class DispatchRequest:
    instance_id: str
    """The agent's unique id."""

    tool_name: str
    """Name of the tool the agent wants to call, e.g. "mcp_call"."""

    tool_version: str = "1"
    """Tool version. Bare numeric string ("1", not "v1") to match the
    registry's key composer."""

    args: dict[str, Any] = field(default_factory=dict)
    """Arguments the agent wants to pass to the tool. Validated by the
    tool's own validate() if registered."""

    session_id: str = ""
    """Session identifier. Used by CallCounter + TaskUsageCap."""

    task_caps: dict[str, Any] | None = None
    """Operator-supplied per-task caps. E.g. {"usage_cap_tokens": 100000}."""


# ─────────────────────────────────────────────────────────────────────────
# StepResult — uniform verdict shape per gate.
# ─────────────────────────────────────────────────────────────────────────
Verdict = Literal["GO", "REFUSE", "PENDING"]


@dataclass(frozen=True)
class StepResult:
    """One gate's verdict."""

    verdict: Verdict
    """GO → continue to next gate. REFUSE / PENDING → terminate pipeline."""

    reason: str | None = None
    """Machine-readable refusal code, e.g. "hardware_quarantined"."""

    detail: str | None = None
    """Human-readable detail. Shown in audit chain + dispatcher errors."""

    gate_source: str | None = None
    """For PENDING verdicts: which gate elevated. constraint / genre /
    constraint+genre / posture."""

    @classmethod
    def go(cls, detail: str | None = None) -> "StepResult":
        return cls(verdict="GO", detail=detail)

    @classmethod
    def refuse(cls, reason: str, detail: str) -> "StepResult":
        return cls(verdict="REFUSE", reason=reason, detail=detail)

    @classmethod
    def pending(cls, gate_source: str, detail: str | None = None) -> "StepResult":
        return cls(verdict="PENDING", gate_source=gate_source, detail=detail)

    @property
    def terminal(self) -> bool:
        return self.verdict != "GO"


# ─────────────────────────────────────────────────────────────────────────
# DispatchResult — outcome of running the full pipeline.
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class DispatchResult:
    """Common base for the three terminal verdicts.

    Concrete subclasses below preserve the kernel ABI (DispatchSucceeded,
    DispatchRefused, DispatchPendingApproval).
    """

    kind: Literal["go", "refuse", "pending"]
    trace: list[tuple[str, StepResult]] = field(default_factory=list)
    """One entry per gate that fired. (gate_name, result)."""

    pipeline_ms: float = 0.0
    """Total elapsed time across all gates, in milliseconds."""


@dataclass
class DispatchSucceeded(DispatchResult):
    kind: Literal["go"] = "go"


@dataclass
class DispatchRefused(DispatchResult):
    kind: Literal["refuse"] = "refuse"
    reason: str = ""
    detail: str = ""


@dataclass
class DispatchPendingApproval(DispatchResult):
    kind: Literal["pending"] = "pending"
    gate_source: str = ""
    detail: str = ""


# ─────────────────────────────────────────────────────────────────────────
# DispatchContext — internal state threaded through the pipeline.
# Steps may mutate accumulated fields (tool, resolved). Inputs are
# read-only by convention.
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class DispatchContext:
    # inputs
    request: DispatchRequest
    agent: dict[str, Any]
    """Agent record. Shape: {role, genre, initiative, posture, provider,
    hardware_bound, hw_matches, constitution_tools (list of "name.v1")}."""
    constitution: dict[str, Any]
    """Loaded constitution.yaml."""
    registry: dict[str, dict[str, Any]]
    """Tool registry keyed by "name.v1"."""
    mcp_registry: dict[str, Any]
    """Merged MCP server registry."""
    session_calls: int = 0
    session_tokens: int = 0

    # accumulated
    tool: dict[str, Any] | None = None
    resolved: dict[str, Any] | None = None
    """{side_effects, constraints, applied_rules}."""

    @property
    def key(self) -> str:
        return f"{self.request.tool_name}.v{self.request.tool_version}"
