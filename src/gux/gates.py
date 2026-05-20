"""The twelve governance gates.

Each gate is a small class with one method: evaluate(ctx) -> StepResult.
Order matters — the pipeline walks them in declaration order and the
first terminal verdict short-circuits.

This module's contract is the kernel ABI surface for "tool dispatch
protocol" — re-ordering, renaming, or removing a gate is a breaking
change. Adding a gate at a new position is non-breaking.

Semantics mirror forest_soul_forge/tools/governance_pipeline.py — the
original kernel this was extracted from.
"""
from __future__ import annotations

from dataclasses import dataclass

from gux.types import DispatchContext, StepResult


# ─────────────────────────────────────────────────────────────────────────
# Side-effects tier ladder + initiative ladder.
# ─────────────────────────────────────────────────────────────────────────
SIDE_EFFECT_RANK = {
    "read_only": 0,
    "registry_write": 1,
    "filesystem": 2,
    "network": 3,
    "external": 4,
}

# Defensive default for a missing genre: clamp to read_only only.
DEFAULT_GENRE_CEILING = "read_only"

# Per-genre ceiling — the maximum side_effects tier this role can dispatch.
# Operators may override via genres.yaml; this is the kernel's defaults.
GENRE_CEILINGS = {
    "research": "network",
    "operations": "filesystem",
    "software-engineering": "external",
    "persistent-assistant": "external",
    "security-low": "read_only",
    "security-mid": "filesystem",
    "security-high": "external",
}

INITIATIVE_LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")


def _init_index(level: str) -> int:
    try:
        return INITIATIVE_LEVELS.index(level)
    except ValueError:
        return 0  # fail-closed


# ─────────────────────────────────────────────────────────────────────────
# Gate 01 · HardwareQuarantine
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class HardwareQuarantineGate:
    name = "HardwareQuarantine"
    id = "hardware_quarantine"

    def evaluate(self, ctx: DispatchContext) -> StepResult:
        if ctx.agent.get("hardware_bound") and not ctx.agent.get("hw_matches", True):
            return StepResult.refuse(
                "hardware_quarantined",
                "agent's constitution is hardware-bound to a different "
                "machine fingerprint — operator must unbind or mint a "
                "roaming passport",
            )
        return StepResult.go()


# ─────────────────────────────────────────────────────────────────────────
# Gate 02 · TaskUsageCap
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class TaskUsageCapGate:
    name = "TaskUsageCap"
    id = "task_usage_cap"

    def evaluate(self, ctx: DispatchContext) -> StepResult:
        caps = ctx.request.task_caps
        if not caps:
            return StepResult.go("no task_caps supplied")
        cap = caps.get("usage_cap_tokens")
        if isinstance(cap, int) and cap > 0 and ctx.session_tokens >= cap:
            return StepResult.refuse(
                "task_usage_cap_exceeded",
                f"session has consumed {ctx.session_tokens} tokens; "
                f"operator-supplied usage_cap_tokens={cap}",
            )
        return StepResult.go()


# ─────────────────────────────────────────────────────────────────────────
# Gate 03 · ToolLookup
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class ToolLookupGate:
    name = "ToolLookup"
    id = "tool_lookup"

    def evaluate(self, ctx: DispatchContext) -> StepResult:
        tool = ctx.registry.get(ctx.key)
        if tool is None:
            return StepResult.refuse(
                "unknown_tool",
                f"no tool registered for {ctx.key} (registered: "
                f"{list(ctx.registry)})",
            )
        ctx.tool = tool
        return StepResult.go()


# ─────────────────────────────────────────────────────────────────────────
# Gate 04 · ArgsValidation
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class ArgsValidationGate:
    name = "ArgsValidation"
    id = "args_validation"

    def evaluate(self, ctx: DispatchContext) -> StepResult:
        required = (ctx.tool or {}).get("required", []) or []
        args = ctx.request.args or {}
        for key in required:
            if key not in args or args[key] in (None, ""):
                return StepResult.refuse(
                    "bad_args",
                    f"missing required argument '{key}' for {ctx.key}",
                )
        return StepResult.go()


# ─────────────────────────────────────────────────────────────────────────
# Gate 05 · ConstraintResolution — reads the agent's constitution.
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class ConstraintResolutionGate:
    name = "ConstraintResolution"
    id = "constraint_resolution"

    def evaluate(self, ctx: DispatchContext) -> StepResult:
        allowed = ctx.agent.get("constitution_tools") or []
        if ctx.key not in allowed:
            return StepResult.refuse(
                "tool_not_in_constitution",
                f"agent's constitution does not list {ctx.key} — re-birth "
                "or POST /agents/{instance_id}/tools/grant to grant access",
            )
        # Build the resolved-constraints object that downstream gates mutate.
        ctx.resolved = {
            "side_effects": ctx.tool.get("side_effects", "read_only"),
            "constraints": {
                "requires_human_approval": False,
                "max_calls_per_session": ctx.constitution.get(
                    "policies", {}
                ).get("max_calls_per_session", 200),
            },
            "applied_rules": [
                f"role:{ctx.agent.get('role', 'unknown')}",
                f"genre:{ctx.agent.get('genre', 'unknown')}",
            ],
        }
        return StepResult.go()


# ─────────────────────────────────────────────────────────────────────────
# Gate 06 · PostureOverride — per-provider tightening only.
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class PostureOverrideGate:
    name = "PostureOverride"
    id = "posture_override"

    def evaluate(self, ctx: DispatchContext) -> StepResult:
        overrides = (
            ctx.constitution.get("provider_posture_overrides") or {}
        ).get(ctx.agent.get("provider"), {})
        tool_overrides = (overrides.get("tools") or {}).get(ctx.request.tool_name)
        if not tool_overrides:
            return StepResult.go("no tightenings for this provider")
        constraints = (tool_overrides.get("constraints") or {})
        for k, v in constraints.items():
            # only TIGHTEN — never loosen. We treat lower numbers as tighter
            # for numeric constraints, and any truthy bool for human approval.
            current = ctx.resolved["constraints"].get(k)
            # CHECK bool BEFORE int: bool is a subclass of int in Python.
            # isinstance(True, int) is True, so checking int first would
            # route every bool override through the numeric-tighten branch
            # and "True < False" evaluates False — silent no-op on every
            # forces-approval override. Test:
            # TestPostureOverride.test_override_forces_human_approval.
            if isinstance(v, bool):
                if v:  # forcing approval is always tighter
                    ctx.resolved["constraints"][k] = True
            elif isinstance(v, int) and isinstance(current, int):
                if v < current:
                    ctx.resolved["constraints"][k] = v
        ctx.resolved["applied_rules"].append(
            f"posture_override:{ctx.agent.get('provider')}"
        )
        return StepResult.go(f"tightened for {ctx.agent.get('provider')}")


# ─────────────────────────────────────────────────────────────────────────
# Gate 07 · GenreFloor — side-effects ceiling.
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class GenreFloorGate:
    name = "GenreFloor"
    id = "genre_floor"

    def evaluate(self, ctx: DispatchContext) -> StepResult:
        ceil = GENRE_CEILINGS.get(ctx.agent.get("genre"), DEFAULT_GENRE_CEILING)
        tier = ctx.resolved["side_effects"]
        if SIDE_EFFECT_RANK[tier] > SIDE_EFFECT_RANK[ceil]:
            return StepResult.refuse(
                "genre_floor_violated",
                f"{ctx.agent.get('genre')} ceiling is {ceil}; "
                f"{ctx.key} is {tier}",
            )
        return StepResult.go()


# ─────────────────────────────────────────────────────────────────────────
# Gate 08 · InitiativeFloor — L0–L5 autonomy ladder.
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class InitiativeFloorGate:
    name = "InitiativeFloor"
    id = "initiative_floor"

    def evaluate(self, ctx: DispatchContext) -> StepResult:
        required = (ctx.tool or {}).get("required_initiative_level")
        if not required:
            return StepResult.go()
        agent_level = ctx.agent.get("initiative", "L0")
        if _init_index(agent_level) < _init_index(required):
            return StepResult.refuse(
                "initiative_floor_violated",
                f"{ctx.key} requires initiative_level ≥ {required}; agent "
                f"is {agent_level}",
            )
        return StepResult.go(
            f"tool requires {required}, agent is {agent_level}"
        )


# ─────────────────────────────────────────────────────────────────────────
# Gate 09 · CallCounter — per-session max_calls (read-only check).
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class CallCounterGate:
    name = "CallCounter"
    id = "call_counter"

    def evaluate(self, ctx: DispatchContext) -> StepResult:
        max_calls = ctx.resolved["constraints"].get("max_calls_per_session", 0)
        if max_calls and ctx.session_calls >= max_calls:
            return StepResult.refuse(
                "max_calls_exceeded",
                f"session {ctx.request.session_id} has "
                f"{ctx.session_calls}/{max_calls} calls used",
            )
        return StepResult.go(f"{ctx.session_calls}/{max_calls} calls used")


# ─────────────────────────────────────────────────────────────────────────
# Gate 10 · McpPerToolApproval — mirror plugin manifest's approval flag.
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class McpPerToolApprovalGate:
    name = "McpPerToolApproval"
    id = "mcp_per_tool_approval"

    def evaluate(self, ctx: DispatchContext) -> StepResult:
        if ctx.request.tool_name != "mcp_call":
            return StepResult.go("tool != mcp_call.v1")
        server = (ctx.request.args or {}).get("server_name")
        target = (ctx.request.args or {}).get("tool_name")
        cfg = (ctx.mcp_registry or {}).get(server) or {}
        per_tool = cfg.get("requires_human_approval_per_tool") or {}
        if per_tool.get(target):
            ctx.resolved["constraints"]["requires_human_approval"] = True
            ctx.resolved["applied_rules"].append(
                f"mcp_per_tool_approval[{server}.{target}]"
            )
            return StepResult.go(
                f"{server}.{target} → requires_human_approval=true"
            )
        return StepResult.go()


# ─────────────────────────────────────────────────────────────────────────
# Gate 11 · ApprovalGate — constraint OR genre policy elevates to PENDING.
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class ApprovalGateGate:
    name = "ApprovalGate"
    id = "approval_gate"

    def evaluate(self, ctx: DispatchContext) -> StepResult:
        constraint_requires = bool(
            ctx.resolved["constraints"].get("requires_human_approval", False)
        )
        side_effects = ctx.resolved["side_effects"]
        # genre policy: security-high needs approval for any non-read_only;
        # persistent-assistant needs approval for network.
        genre = ctx.agent.get("genre")
        genre_requires = (
            (genre == "security-high" and side_effects != "read_only")
            or (genre == "persistent-assistant" and side_effects == "network")
        )
        if constraint_requires or genre_requires:
            source = (
                "constraint+genre"
                if (constraint_requires and genre_requires)
                else ("genre" if genre_requires else "constraint")
            )
            return StepResult.pending(
                source,
                detail=f"gate_source: {source} · side_effects: {side_effects}",
            )
        return StepResult.go()


# ─────────────────────────────────────────────────────────────────────────
# Gate 12 · PostureGate — agent traffic light.
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class PostureGateGate:
    name = "PostureGate"
    id = "posture_gate"

    def evaluate(self, ctx: DispatchContext) -> StepResult:
        tier = ctx.resolved["side_effects"]
        if tier == "read_only":
            return StepResult.go("read_only passes every posture")
        posture = ctx.agent.get("posture", "green")
        if posture == "yellow":
            return StepResult.pending(
                "posture",
                detail="posture=yellow forces pending_approval on "
                "non-read-only (ADR-0045 T1)",
            )
        if posture == "red":
            return StepResult.refuse(
                "posture_red_refuses_writes",
                "posture=red refuses non-read-only outright (probation mode)",
            )
        return StepResult.go()


# ─────────────────────────────────────────────────────────────────────────
# The pipeline, in order. Reordering = breaking ABI change.
# ─────────────────────────────────────────────────────────────────────────
GATES: list = [
    HardwareQuarantineGate(),
    TaskUsageCapGate(),
    ToolLookupGate(),
    ArgsValidationGate(),
    ConstraintResolutionGate(),
    PostureOverrideGate(),
    GenreFloorGate(),
    InitiativeFloorGate(),
    CallCounterGate(),
    McpPerToolApprovalGate(),
    ApprovalGateGate(),
    PostureGateGate(),
]

ALL_GATE_NAMES: tuple[str, ...] = tuple(g.name for g in GATES)
