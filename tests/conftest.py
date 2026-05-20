"""Shared fixtures for G.UX gate tests.

The base_ctx fixture builds a DispatchContext that PASSES every gate
(the happy-path baseline). Per-test, callers mutate one or two fields
to drive REFUSE / PENDING behavior. Keeps each test focused on the
exact contract the gate is responsible for.
"""
from __future__ import annotations

import pytest

from gux.types import DispatchContext, DispatchRequest


@pytest.fixture
def base_request() -> DispatchRequest:
    """Default request — memory_recall.v1 against a single agent. Cheap
    read-only tool that every gate should pass cleanly."""
    return DispatchRequest(
        instance_id="agent-a",
        tool_name="memory_recall",
        tool_version="1",
        args={"query": "what did we decide?"},
        session_id="sess-001",
    )


@pytest.fixture
def base_registry() -> dict[str, dict]:
    """Minimal tool registry with the memory_recall fixture entry."""
    return {
        "memory_recall.v1": {
            "name": "memory_recall",
            "version": "1",
            "side_effects": "read_only",
            "required": ["query"],
        },
    }


@pytest.fixture
def base_agent() -> dict:
    """Default agent: research genre, L2 initiative, green posture,
    constitution allows memory_recall."""
    return {
        "role": "test_author",
        "genre": "research",
        "initiative": "L2",
        "posture": "green",
        "provider": "ollama",
        "hardware_bound": False,
        "hw_matches": True,
        "constitution_tools": ["memory_recall.v1"],
    }


@pytest.fixture
def base_constitution() -> dict:
    """Minimal constitution with default policies."""
    return {
        "policies": {
            "max_calls_per_session": 200,
        },
    }


@pytest.fixture
def base_ctx(
    base_request,
    base_agent,
    base_constitution,
    base_registry,
) -> DispatchContext:
    """A pipeline-ready context. Tests mutate one field then call the
    gate under test."""
    return DispatchContext(
        request=base_request,
        agent=base_agent,
        constitution=base_constitution,
        registry=base_registry,
        mcp_registry={},
        session_calls=0,
        session_tokens=0,
    )


@pytest.fixture
def resolved_ctx(base_ctx) -> DispatchContext:
    """Context with ctx.tool + ctx.resolved already populated — what
    later-pipeline gates (Posture, Approval, GenreFloor) see after the
    earlier gates have run."""
    base_ctx.tool = base_ctx.registry["memory_recall.v1"]
    base_ctx.resolved = {
        "side_effects": "read_only",
        "constraints": {
            "requires_human_approval": False,
            "max_calls_per_session": 200,
        },
        "applied_rules": ["role:test_author", "genre:research"],
    }
    return base_ctx
