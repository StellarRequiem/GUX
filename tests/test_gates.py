"""Layer 1 unit tests — every G.UX gate's GO / REFUSE / PENDING contract.

Each gate gets:
  * a happy-path test (verdict=GO)
  * one test per REFUSE / PENDING branch in the gate's code

Tests use the base_ctx fixture (passes every gate by default) and the
resolved_ctx fixture (has ctx.tool + ctx.resolved populated, for the
later-pipeline gates that need those).
"""
from __future__ import annotations

import pytest

from gux.gates import (
    ApprovalGateGate,
    ArgsValidationGate,
    CallCounterGate,
    ConstraintResolutionGate,
    GenreFloorGate,
    HardwareQuarantineGate,
    InitiativeFloorGate,
    McpPerToolApprovalGate,
    PostureGateGate,
    PostureOverrideGate,
    TaskUsageCapGate,
    ToolLookupGate,
    GATES,
    ALL_GATE_NAMES,
)
from gux.types import DispatchRequest


# ─────────────────────────────────────────────────────────────────────────
# Pipeline-shape invariants
# ─────────────────────────────────────────────────────────────────────────

def test_gates_count_is_twelve():
    """The kernel ABI promises exactly 12 gates in declaration order.
    Reordering or removing is a breaking change."""
    assert len(GATES) == 12
    assert len(ALL_GATE_NAMES) == 12


def test_gate_names_match_expected_order():
    """Order matters — first terminal verdict short-circuits. Lock it
    down so refactors don't silently shift gate ordering."""
    assert ALL_GATE_NAMES == (
        "HardwareQuarantine",
        "TaskUsageCap",
        "ToolLookup",
        "ArgsValidation",
        "ConstraintResolution",
        "PostureOverride",
        "GenreFloor",
        "InitiativeFloor",
        "CallCounter",
        "McpPerToolApproval",
        "ApprovalGate",
        "PostureGate",
    )


# ─────────────────────────────────────────────────────────────────────────
# Gate 01 · HardwareQuarantine
# ─────────────────────────────────────────────────────────────────────────

class TestHardwareQuarantine:
    def test_not_hardware_bound_passes(self, base_ctx):
        base_ctx.agent["hardware_bound"] = False
        result = HardwareQuarantineGate().evaluate(base_ctx)
        assert result.verdict == "GO"

    def test_hardware_bound_matching_passes(self, base_ctx):
        base_ctx.agent["hardware_bound"] = True
        base_ctx.agent["hw_matches"] = True
        result = HardwareQuarantineGate().evaluate(base_ctx)
        assert result.verdict == "GO"

    def test_hardware_bound_mismatch_refuses(self, base_ctx):
        base_ctx.agent["hardware_bound"] = True
        base_ctx.agent["hw_matches"] = False
        result = HardwareQuarantineGate().evaluate(base_ctx)
        assert result.verdict == "REFUSE"
        assert result.reason == "hardware_quarantined"


# ─────────────────────────────────────────────────────────────────────────
# Gate 02 · TaskUsageCap
# ─────────────────────────────────────────────────────────────────────────

class TestTaskUsageCap:
    def test_no_caps_passes(self, base_ctx):
        base_ctx.request.task_caps = None
        result = TaskUsageCapGate().evaluate(base_ctx)
        assert result.verdict == "GO"

    def test_under_cap_passes(self, base_ctx):
        base_ctx.request.task_caps = {"usage_cap_tokens": 1000}
        base_ctx.session_tokens = 500
        result = TaskUsageCapGate().evaluate(base_ctx)
        assert result.verdict == "GO"

    def test_at_cap_refuses(self, base_ctx):
        base_ctx.request.task_caps = {"usage_cap_tokens": 1000}
        base_ctx.session_tokens = 1000
        result = TaskUsageCapGate().evaluate(base_ctx)
        assert result.verdict == "REFUSE"
        assert result.reason == "task_usage_cap_exceeded"

    def test_over_cap_refuses(self, base_ctx):
        base_ctx.request.task_caps = {"usage_cap_tokens": 1000}
        base_ctx.session_tokens = 1500
        result = TaskUsageCapGate().evaluate(base_ctx)
        assert result.verdict == "REFUSE"

    def test_cap_zero_disabled_passes(self, base_ctx):
        """cap=0 is documented as disabled, not strictly negative."""
        base_ctx.request.task_caps = {"usage_cap_tokens": 0}
        base_ctx.session_tokens = 999
        result = TaskUsageCapGate().evaluate(base_ctx)
        assert result.verdict == "GO"


# ─────────────────────────────────────────────────────────────────────────
# Gate 03 · ToolLookup
# ─────────────────────────────────────────────────────────────────────────

class TestToolLookup:
    def test_known_tool_passes_and_populates_ctx_tool(self, base_ctx):
        result = ToolLookupGate().evaluate(base_ctx)
        assert result.verdict == "GO"
        assert base_ctx.tool == base_ctx.registry["memory_recall.v1"]

    def test_unknown_tool_refuses(self, base_ctx):
        base_ctx.request.tool_name = "does_not_exist"
        result = ToolLookupGate().evaluate(base_ctx)
        assert result.verdict == "REFUSE"
        assert result.reason == "unknown_tool"

    def test_wrong_version_refuses(self, base_ctx):
        """Versioning is part of the key — memory_recall.v2 isn't v1."""
        base_ctx.request.tool_version = "99"
        result = ToolLookupGate().evaluate(base_ctx)
        assert result.verdict == "REFUSE"


# ─────────────────────────────────────────────────────────────────────────
# Gate 04 · ArgsValidation
# ─────────────────────────────────────────────────────────────────────────

class TestArgsValidation:
    def test_no_required_fields_passes(self, base_ctx):
        base_ctx.tool = {"required": []}
        result = ArgsValidationGate().evaluate(base_ctx)
        assert result.verdict == "GO"

    def test_all_required_present_passes(self, resolved_ctx):
        result = ArgsValidationGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"

    def test_missing_required_refuses(self, resolved_ctx):
        resolved_ctx.request.args = {}
        result = ArgsValidationGate().evaluate(resolved_ctx)
        assert result.verdict == "REFUSE"
        assert result.reason == "bad_args"

    def test_empty_string_arg_refuses(self, resolved_ctx):
        resolved_ctx.request.args = {"query": ""}
        result = ArgsValidationGate().evaluate(resolved_ctx)
        assert result.verdict == "REFUSE"

    def test_none_arg_refuses(self, resolved_ctx):
        resolved_ctx.request.args = {"query": None}
        result = ArgsValidationGate().evaluate(resolved_ctx)
        assert result.verdict == "REFUSE"


# ─────────────────────────────────────────────────────────────────────────
# Gate 05 · ConstraintResolution
# ─────────────────────────────────────────────────────────────────────────

class TestConstraintResolution:
    def test_tool_in_constitution_passes_and_populates_resolved(self, base_ctx):
        base_ctx.tool = base_ctx.registry["memory_recall.v1"]
        result = ConstraintResolutionGate().evaluate(base_ctx)
        assert result.verdict == "GO"
        assert base_ctx.resolved is not None
        assert base_ctx.resolved["side_effects"] == "read_only"
        assert (
            base_ctx.resolved["constraints"]["max_calls_per_session"] == 200
        )

    def test_tool_not_in_constitution_refuses(self, base_ctx):
        base_ctx.tool = base_ctx.registry["memory_recall.v1"]
        base_ctx.agent["constitution_tools"] = ["other_tool.v1"]
        result = ConstraintResolutionGate().evaluate(base_ctx)
        assert result.verdict == "REFUSE"
        assert result.reason == "tool_not_in_constitution"

    def test_empty_constitution_tools_refuses(self, base_ctx):
        base_ctx.tool = base_ctx.registry["memory_recall.v1"]
        base_ctx.agent["constitution_tools"] = []
        result = ConstraintResolutionGate().evaluate(base_ctx)
        assert result.verdict == "REFUSE"


# ─────────────────────────────────────────────────────────────────────────
# Gate 06 · PostureOverride
# ─────────────────────────────────────────────────────────────────────────

class TestPostureOverride:
    def test_no_overrides_passes(self, resolved_ctx):
        result = PostureOverrideGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"

    def test_overrides_for_other_tool_passes(self, resolved_ctx):
        resolved_ctx.constitution["provider_posture_overrides"] = {
            "ollama": {"tools": {"other_tool": {"constraints": {}}}},
        }
        result = PostureOverrideGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"

    def test_override_tightens_numeric_constraint(self, resolved_ctx):
        resolved_ctx.constitution["provider_posture_overrides"] = {
            "ollama": {
                "tools": {
                    "memory_recall": {
                        "constraints": {"max_calls_per_session": 50}
                    }
                }
            },
        }
        result = PostureOverrideGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"
        # 50 < 200 → tightened down to 50
        assert resolved_ctx.resolved["constraints"]["max_calls_per_session"] == 50

    def test_override_does_not_loosen_numeric_constraint(self, resolved_ctx):
        resolved_ctx.constitution["provider_posture_overrides"] = {
            "ollama": {
                "tools": {
                    "memory_recall": {
                        "constraints": {"max_calls_per_session": 500}
                    }
                }
            },
        }
        result = PostureOverrideGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"
        # 500 > 200 → must NOT loosen; stays at 200
        assert resolved_ctx.resolved["constraints"]["max_calls_per_session"] == 200

    def test_override_forces_human_approval(self, resolved_ctx):
        resolved_ctx.constitution["provider_posture_overrides"] = {
            "ollama": {
                "tools": {
                    "memory_recall": {
                        "constraints": {"requires_human_approval": True}
                    }
                }
            },
        }
        result = PostureOverrideGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"
        assert resolved_ctx.resolved["constraints"]["requires_human_approval"] is True


# ─────────────────────────────────────────────────────────────────────────
# Gate 07 · GenreFloor
# ─────────────────────────────────────────────────────────────────────────

class TestGenreFloor:
    def test_within_ceiling_passes(self, resolved_ctx):
        # research ceiling = network; resolved.side_effects = read_only
        result = GenreFloorGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"

    def test_at_ceiling_passes(self, resolved_ctx):
        # research = network ceiling
        resolved_ctx.resolved["side_effects"] = "network"
        result = GenreFloorGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"

    def test_above_ceiling_refuses(self, resolved_ctx):
        # research = network (rank 3); external (rank 4) is above
        resolved_ctx.resolved["side_effects"] = "external"
        result = GenreFloorGate().evaluate(resolved_ctx)
        assert result.verdict == "REFUSE"
        assert result.reason == "genre_floor_violated"

    def test_security_low_clamped_to_read_only(self, resolved_ctx):
        resolved_ctx.agent["genre"] = "security-low"
        resolved_ctx.resolved["side_effects"] = "filesystem"
        result = GenreFloorGate().evaluate(resolved_ctx)
        assert result.verdict == "REFUSE"

    def test_unknown_genre_defaults_to_read_only_ceiling(self, resolved_ctx):
        """DEFAULT_GENRE_CEILING = read_only — defensive fail-closed."""
        resolved_ctx.agent["genre"] = "made-up-genre"
        resolved_ctx.resolved["side_effects"] = "filesystem"
        result = GenreFloorGate().evaluate(resolved_ctx)
        assert result.verdict == "REFUSE"


# ─────────────────────────────────────────────────────────────────────────
# Gate 08 · InitiativeFloor
# ─────────────────────────────────────────────────────────────────────────

class TestInitiativeFloor:
    def test_no_required_passes(self, resolved_ctx):
        # base tool doesn't have required_initiative_level
        result = InitiativeFloorGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"

    def test_at_required_passes(self, resolved_ctx):
        resolved_ctx.tool["required_initiative_level"] = "L2"
        resolved_ctx.agent["initiative"] = "L2"
        result = InitiativeFloorGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"

    def test_above_required_passes(self, resolved_ctx):
        resolved_ctx.tool["required_initiative_level"] = "L1"
        resolved_ctx.agent["initiative"] = "L3"
        result = InitiativeFloorGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"

    def test_below_required_refuses(self, resolved_ctx):
        resolved_ctx.tool["required_initiative_level"] = "L3"
        resolved_ctx.agent["initiative"] = "L1"
        result = InitiativeFloorGate().evaluate(resolved_ctx)
        assert result.verdict == "REFUSE"
        assert result.reason == "initiative_floor_violated"

    def test_unknown_initiative_fails_closed(self, resolved_ctx):
        """Unknown initiative levels fail closed (treated as L0)."""
        resolved_ctx.tool["required_initiative_level"] = "L1"
        resolved_ctx.agent["initiative"] = "ZZ"
        result = InitiativeFloorGate().evaluate(resolved_ctx)
        assert result.verdict == "REFUSE"


# ─────────────────────────────────────────────────────────────────────────
# Gate 09 · CallCounter
# ─────────────────────────────────────────────────────────────────────────

class TestCallCounter:
    def test_under_max_passes(self, resolved_ctx):
        resolved_ctx.session_calls = 50
        result = CallCounterGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"

    def test_at_max_refuses(self, resolved_ctx):
        resolved_ctx.session_calls = 200
        result = CallCounterGate().evaluate(resolved_ctx)
        assert result.verdict == "REFUSE"
        assert result.reason == "max_calls_exceeded"

    def test_zero_max_disabled_passes(self, resolved_ctx):
        resolved_ctx.resolved["constraints"]["max_calls_per_session"] = 0
        resolved_ctx.session_calls = 999
        result = CallCounterGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"


# ─────────────────────────────────────────────────────────────────────────
# Gate 10 · McpPerToolApproval
# ─────────────────────────────────────────────────────────────────────────

class TestMcpPerToolApproval:
    def test_non_mcp_tool_passes(self, resolved_ctx):
        # base request is memory_recall, not mcp_call
        result = McpPerToolApprovalGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"

    def test_mcp_call_without_per_tool_config_passes(self, resolved_ctx):
        resolved_ctx.request.tool_name = "mcp_call"
        resolved_ctx.request.args = {
            "server_name": "filesystem",
            "tool_name": "read_file",
        }
        result = McpPerToolApprovalGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"

    def test_mcp_call_with_per_tool_true_sets_approval(self, resolved_ctx):
        resolved_ctx.request.tool_name = "mcp_call"
        resolved_ctx.request.args = {
            "server_name": "filesystem",
            "tool_name": "write_file",
        }
        resolved_ctx.mcp_registry["filesystem"] = {
            "requires_human_approval_per_tool": {"write_file": True},
        }
        result = McpPerToolApprovalGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"
        assert (
            resolved_ctx.resolved["constraints"]["requires_human_approval"]
            is True
        )


# ─────────────────────────────────────────────────────────────────────────
# Gate 11 · ApprovalGate
# ─────────────────────────────────────────────────────────────────────────

class TestApprovalGate:
    def test_no_approval_required_passes(self, resolved_ctx):
        result = ApprovalGateGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"

    def test_constraint_requires_approval_pending(self, resolved_ctx):
        resolved_ctx.resolved["constraints"]["requires_human_approval"] = True
        result = ApprovalGateGate().evaluate(resolved_ctx)
        assert result.verdict == "PENDING"
        assert result.gate_source == "constraint"

    def test_security_high_non_readonly_pending(self, resolved_ctx):
        resolved_ctx.agent["genre"] = "security-high"
        resolved_ctx.resolved["side_effects"] = "filesystem"
        result = ApprovalGateGate().evaluate(resolved_ctx)
        assert result.verdict == "PENDING"
        assert result.gate_source == "genre"

    def test_security_high_read_only_passes(self, resolved_ctx):
        resolved_ctx.agent["genre"] = "security-high"
        # read_only by default
        result = ApprovalGateGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"

    def test_persistent_assistant_network_pending(self, resolved_ctx):
        resolved_ctx.agent["genre"] = "persistent-assistant"
        resolved_ctx.resolved["side_effects"] = "network"
        result = ApprovalGateGate().evaluate(resolved_ctx)
        assert result.verdict == "PENDING"
        assert result.gate_source == "genre"

    def test_both_constraint_and_genre_pending_combined_source(self, resolved_ctx):
        resolved_ctx.agent["genre"] = "security-high"
        resolved_ctx.resolved["side_effects"] = "filesystem"
        resolved_ctx.resolved["constraints"]["requires_human_approval"] = True
        result = ApprovalGateGate().evaluate(resolved_ctx)
        assert result.verdict == "PENDING"
        assert result.gate_source == "constraint+genre"


# ─────────────────────────────────────────────────────────────────────────
# Gate 12 · PostureGate
# ─────────────────────────────────────────────────────────────────────────

class TestPostureGate:
    def test_read_only_with_any_posture_passes(self, resolved_ctx):
        # default side_effects = read_only
        for posture in ("green", "yellow", "red"):
            resolved_ctx.agent["posture"] = posture
            result = PostureGateGate().evaluate(resolved_ctx)
            assert result.verdict == "GO", f"posture={posture} should GO on read_only"

    def test_green_with_non_readonly_passes(self, resolved_ctx):
        resolved_ctx.agent["posture"] = "green"
        resolved_ctx.resolved["side_effects"] = "network"
        result = PostureGateGate().evaluate(resolved_ctx)
        assert result.verdict == "GO"

    def test_yellow_with_non_readonly_pending(self, resolved_ctx):
        resolved_ctx.agent["posture"] = "yellow"
        resolved_ctx.resolved["side_effects"] = "filesystem"
        result = PostureGateGate().evaluate(resolved_ctx)
        assert result.verdict == "PENDING"
        assert result.gate_source == "posture"

    def test_red_with_non_readonly_refuses(self, resolved_ctx):
        resolved_ctx.agent["posture"] = "red"
        resolved_ctx.resolved["side_effects"] = "filesystem"
        result = PostureGateGate().evaluate(resolved_ctx)
        assert result.verdict == "REFUSE"
        assert result.reason == "posture_red_refuses_writes"
