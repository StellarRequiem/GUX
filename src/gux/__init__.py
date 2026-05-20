"""G.UX — Governor User Experience.

A drop-in governance kernel for LLM tool dispatch. Twelve ordered gates
decide GO / REFUSE / PENDING for every tool call before it executes.

Public surface:

    from gux import Governor, DispatchRequest

    governor = Governor.from_yaml(constitution="./constitution.yaml")

    result = governor.dispatch(DispatchRequest(
        instance_id="my-agent-01",
        tool_name="memory_recall",
        tool_version="1",
        args={"query": "..."},
        session_id="sess_abc123",
    ))

    if result.kind == "go":
        # execute the tool
        ...
    elif result.kind == "pending":
        # queue for human approval
        ...
    elif result.kind == "refuse":
        # log and surface the refusal reason
        ...
"""

from gux.governor import Governor
from gux.types import (
    DispatchRequest,
    DispatchResult,
    DispatchSucceeded,
    DispatchRefused,
    DispatchPendingApproval,
    StepResult,
)
from gux.gates import GATES, ALL_GATE_NAMES

__version__ = "0.5.0"
__all__ = [
    "Governor",
    "DispatchRequest",
    "DispatchResult",
    "DispatchSucceeded",
    "DispatchRefused",
    "DispatchPendingApproval",
    "StepResult",
    "GATES",
    "ALL_GATE_NAMES",
    "__version__",
]
