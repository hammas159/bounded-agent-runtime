"""The bounded agent loop.

Structure:

    while True:
        budget.check()              <- before the step, so nothing runs over budget
        action = planner.next(...)  <- may be a model, may be a script
        budget.record_step(fp)      <- counts, and detects repetition
        result = registry.call(...) <- may raise ToolError or ApprovalRequired
        observe

The planner is an interface rather than a hardcoded LLM call. That is not
abstraction for its own sake: it is what makes containment testable. A scripted
planner that always emits the same action, or always fails, or never terminates,
lets the chaos suite prove the runtime holds - deterministically, in milliseconds,
with no model and no API key.
"""

from __future__ import annotations

import enum
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..budget import Budget, BudgetExceeded
from ..observe.audit import AuditLog
from ..tools.registry import ApprovalRequired, ToolError, ToolRegistry


class Outcome(enum.StrEnum):
    COMPLETED = "completed"
    BUDGET_STOP = "budget_stop"
    NEEDS_APPROVAL = "needs_approval"
    FAILED = "failed"


@dataclass
class Action:
    """One decision. `finish` ends the run; anything else is a tool call."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""

    def fingerprint(self) -> str:
        """Identity of the action, for loop detection. Argument order must not matter."""
        return f"{self.tool}:{json.dumps(self.args, sort_keys=True, default=str)}"


class Planner(Protocol):
    def next_action(self, goal: str, history: list[dict]) -> Action: ...


@dataclass
class Result:
    outcome: Outcome
    answer: str = ""
    reason: str = ""
    steps: int = 0
    usd: float = 0.0
    seconds: float = 0.0
    history: list[dict] = field(default_factory=list)
    run_id: str = ""
    pending_approval: dict | None = None


class Runtime:
    """Runs a planner against a toolset, inside a budget it cannot influence."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        budget_factory: Callable[[], Budget] = Budget,
        audit_dir: str = "runs",
        tenant: str = "default",
        quotas=None,
    ) -> None:
        self.registry = registry
        self.budget_factory = budget_factory
        self.audit_dir = audit_dir
        self.tenant = tenant
        self.quotas = quotas

    def run(self, goal: str, planner: Planner, *, approvals: set[str] | None = None) -> Result:
        approvals = approvals or set()
        budget = self.budget_factory()
        log = AuditLog(self.audit_dir, tenant=self.tenant)
        history: list[dict] = []

        if self.quotas is not None:
            # Raised before any work: a tenant over quota should cost nothing.
            self.quotas.check_and_start(self.tenant)

        log.record("start", goal=goal, limits=budget.remaining())

        while True:
            try:
                budget.check()
            except BudgetExceeded as stop:
                log.record("budget_stop", limit_kind=stop.kind, limit=stop.limit, used=stop.used)
                return self._finish(Outcome.BUDGET_STOP, str(stop), budget, history, log)

            try:
                action = planner.next_action(goal, history)
            except Exception as exc:
                log.record("planner_error", error=str(exc))
                return self._finish(Outcome.FAILED, f"planner failed: {exc}", budget, history, log)

            try:
                budget.record_step(action.fingerprint())
            except BudgetExceeded as stop:
                # Loop detection lands here: the step that would have repeated is not run.
                log.record("budget_stop", limit_kind=stop.kind, limit=stop.limit, used=stop.used)
                return self._finish(Outcome.BUDGET_STOP, str(stop), budget, history, log)

            log.record(
                "step",
                n=budget.steps,
                tool=action.tool,
                args=action.args,
                reasoning=action.reasoning,
            )

            if action.tool == "finish":
                answer = str(action.args.get("answer", ""))
                return self._finish(Outcome.COMPLETED, "", budget, history, log, answer=answer)

            tool = self.registry.tools.get(action.tool)
            budget.record_tool_call()
            if tool is not None:
                budget.record_cost(tool.usd_per_call)
                if self.quotas is not None:
                    self.quotas.record_spend(self.tenant, tool.usd_per_call)

            try:
                observation = self.registry.call(
                    action.tool, action.args, approved=action.tool in approvals
                )
                log.record(
                    "tool_call", tool=action.tool, ok=True, observation=str(observation)[:500]
                )
                history.append(
                    {"action": action.tool, "args": action.args, "observation": observation}
                )

            except ApprovalRequired as gate:
                # Not a failure. The run pauses, intact, and waits for a human.
                log.record("approval", tool=gate.tool, tier=gate.tier.name, args=gate.tool_args)
                result = self._finish(Outcome.NEEDS_APPROVAL, str(gate), budget, history, log)
                result.pending_approval = {
                    "tool": gate.tool,
                    "tier": gate.tier.name,
                    "args": gate.tool_args,
                }
                return result

            except ToolError as exc:
                # A failing tool is an observation, not a crash. The agent gets to
                # react - and the budget keeps counting while it does.
                log.record("tool_error", tool=action.tool, error=str(exc))
                history.append(
                    {"action": action.tool, "args": action.args, "observation": f"ERROR: {exc}"}
                )

    def _finish(self, outcome, reason, budget, history, log, answer: str = "") -> Result:
        log.record(
            "finish",
            outcome=outcome.value,
            reason=reason,
            steps=budget.steps,
            usd=round(budget.usd, 6),
            seconds=round(budget.elapsed, 3),
        )
        return Result(
            outcome=outcome,
            answer=answer,
            reason=reason,
            steps=budget.steps,
            usd=round(budget.usd, 6),
            seconds=round(budget.elapsed, 3),
            history=history,
            run_id=log.run_id,
        )
