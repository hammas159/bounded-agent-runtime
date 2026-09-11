"""Containment tests.

Every one asserts that a misbehaving agent is stopped *by the runtime*. None of them
uses a model: the point is that containment does not depend on the agent cooperating,
so the agent is replaced with something that definitely will not.
"""

from __future__ import annotations

import pytest

from bar.budget import Budget
from bar.observe.audit import AuditLog
from bar.observe.quotas import QuotaExceeded, QuotaManager, TenantQuota
from bar.runtime.loop import Outcome, Runtime
from bar.tools.registry import RiskTier

from .planners import (
    BrokenPlanner, Expensive, Hallucinates, NeverFinishes, Repeats, Slow,
    SendsThenFinishes, Wellbehaved, WantsIrreversible,
)
from .toolset import SIDE_EFFECTS, build_registry


def runtime(tmp_path, budget: Budget | None = None, **reg_kwargs) -> Runtime:
    return Runtime(
        build_registry(**reg_kwargs),
        budget_factory=(lambda: budget) if budget else Budget,
        audit_dir=str(tmp_path),
    )


def test_agent_that_never_finishes_is_stopped(tmp_path):
    r = runtime(tmp_path, Budget(max_steps=5)).run("go", NeverFinishes())
    assert r.outcome is Outcome.BUDGET_STOP
    assert "steps" in r.reason
    assert r.steps == 5


def test_repetition_is_detected_before_the_step_budget(tmp_path):
    """A looping agent should stop on the loop, not grind through every step."""
    r = runtime(tmp_path, Budget(max_steps=100, max_repeats=3)).run("go", Repeats())
    assert r.outcome is Outcome.BUDGET_STOP
    assert "loop" in r.reason
    assert r.steps == 3


def test_cost_ceiling_holds(tmp_path):
    r = runtime(tmp_path, Budget(max_steps=1000, max_usd=0.2)).run("go", Expensive())
    assert r.outcome is Outcome.BUDGET_STOP
    assert "cost" in r.reason
    # The ceiling may be crossed by at most the last call, never run away from.
    assert r.usd < 0.3


def test_wall_clock_ceiling_holds(tmp_path):
    r = runtime(tmp_path, Budget(max_steps=10_000, max_seconds=0.3)).run("go", Slow())
    assert r.outcome is Outcome.BUDGET_STOP
    assert "time" in r.reason
    assert r.seconds < 2.0


def test_irreversible_action_is_not_performed(tmp_path):
    """The assertion that matters: not that the runtime reported a stop, but that
    the email genuinely was not sent."""
    r = runtime(tmp_path, autonomous_ceiling=RiskTier.WRITE).run("go", WantsIrreversible())
    assert r.outcome is Outcome.NEEDS_APPROVAL
    assert r.pending_approval["tool"] == "send_email"
    assert SIDE_EFFECTS == [], "an IRREVERSIBLE tool executed without approval"


def test_approved_irreversible_action_does_run(tmp_path):
    """The gate must be a gate, not a wall - approval has to let the work through."""
    rt = runtime(tmp_path, autonomous_ceiling=RiskTier.WRITE)
    rt.run("go", SendsThenFinishes(), approvals={"send_email"})
    assert SIDE_EFFECTS == ["email->board@example.com"]


def test_a_failing_tool_does_not_crash_the_run(tmp_path):
    """A dependency being down is an observation, not an exception that escapes."""

    class CallsBrokenTool:
        def next_action(self, goal, history):
            from bar.runtime.loop import Action

            if len(history) < 2:
                return Action(tool="always_fails", args={})
            return Action(tool="finish", args={"answer": "gave up on that tool"})

    r = runtime(tmp_path).run("go", CallsBrokenTool())
    assert r.outcome is Outcome.COMPLETED
    assert any("ERROR" in str(h["observation"]) for h in r.history)


def test_hallucinated_tool_is_recoverable(tmp_path):
    r = runtime(tmp_path).run("go", Hallucinates())
    assert r.outcome is Outcome.COMPLETED
    assert "no such tool" in str(r.history[0]["observation"])


def test_planner_exception_fails_cleanly(tmp_path):
    r = runtime(tmp_path).run("go", BrokenPlanner())
    assert r.outcome is Outcome.FAILED
    assert "planner exploded" in r.reason


def test_wellbehaved_run_completes(tmp_path):
    """Containment must not break the normal path."""
    r = runtime(tmp_path).run("find things", Wellbehaved())
    assert r.outcome is Outcome.COMPLETED
    assert "results for" in r.answer
    assert r.steps == 2


class TestAudit:
    def test_trace_is_complete_even_when_the_run_is_stopped(self, tmp_path):
        r = runtime(tmp_path, Budget(max_steps=4)).run("go", NeverFinishes())
        events = AuditLog.load(tmp_path / f"{r.run_id}.jsonl")
        kinds = [e.kind for e in events]
        assert kinds[0] == "start"
        assert "budget_stop" in kinds
        assert kinds[-1] == "finish"
        assert [e.seq for e in events] == list(range(1, len(events) + 1))

    def test_approval_is_recorded_with_its_arguments(self, tmp_path):
        r = runtime(tmp_path, autonomous_ceiling=RiskTier.WRITE).run("go", WantsIrreversible())
        events = AuditLog.load(tmp_path / f"{r.run_id}.jsonl")
        approval = next(e for e in events if e.kind == "approval")
        assert approval.data["tier"] == "IRREVERSIBLE"
        assert approval.data["args"]["to"] == "board@example.com"


class TestQuotas:
    def test_tenant_run_quota_blocks_before_any_work(self, tmp_path):
        quotas = QuotaManager(default=TenantQuota(max_runs_per_hour=2))
        rt = Runtime(build_registry(), audit_dir=str(tmp_path), quotas=quotas)
        rt.run("go", Wellbehaved())
        rt.run("go", Wellbehaved())
        with pytest.raises(QuotaExceeded):
            rt.run("go", Wellbehaved())

    def test_spend_quota_is_independent_of_per_run_budget(self, tmp_path):
        """Many individually well-behaved runs must not exhaust a tenant."""
        quotas = QuotaManager(default=TenantQuota(max_runs_per_hour=1000,
                                                  max_usd_per_day=0.01))
        rt = Runtime(build_registry(), audit_dir=str(tmp_path), quotas=quotas)
        with pytest.raises(QuotaExceeded):
            for _ in range(50):
                rt.run("go", Expensive())
