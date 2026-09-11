"""Fleet metrics are computed from the audit logs, so they are tested against real
runs rather than fabricated log lines."""

from __future__ import annotations

from bar.budget import Budget
from bar.observe.metrics import fleet_metrics
from bar.runtime import Runtime
from bar.tools.registry import RiskTier

from .planners import Expensive, NeverFinishes, Repeats, Wellbehaved, WantsIrreversible
from .toolset import build_registry


def _fleet(tmp_path):
    def rt(budget=None, **kw):
        return Runtime(
            build_registry(**kw),
            budget_factory=(lambda: budget) if budget else Budget,
            audit_dir=str(tmp_path),
        )

    rt(Budget(max_steps=4)).run("a", NeverFinishes())
    rt(Budget(max_steps=50)).run("b", Repeats())
    rt().run("c", Wellbehaved())
    rt().run("d", Wellbehaved())
    rt(autonomous_ceiling=RiskTier.WRITE).run("e", WantsIrreversible())
    rt(Budget(max_steps=100, max_usd=0.1)).run("f", Expensive())
    return fleet_metrics(tmp_path)


def test_counts_every_run(tmp_path):
    assert _fleet(tmp_path)["runs"] == 6


def test_success_rate(tmp_path):
    assert _fleet(tmp_path)["success_rate"] == round(2 / 6, 4)


def test_stops_are_attributed_to_the_right_ceiling(tmp_path):
    stops = _fleet(tmp_path)["stops_by_kind"]
    assert stops["loop"] == 1 and stops["steps"] == 1 and stops["cost"] == 1


def test_escalation_is_counted_separately_from_failure(tmp_path):
    """An approval pause is not a failure, and conflating them hides governance load."""
    m = _fleet(tmp_path)
    assert m["escalation_rate"] == round(1 / 6, 4)
    assert m["outcomes"]["needs_approval"] == 1


def test_cost_per_success_is_reported(tmp_path):
    """The number that decides whether the system stays switched on."""
    assert _fleet(tmp_path)["usd_per_success"] > 0


def test_a_run_with_no_finish_event_is_counted_as_abandoned(tmp_path):
    """A process killed mid-run is invisible if you only count completed runs."""
    (tmp_path / "dead.jsonl").write_text(
        '{"run_id":"dead","seq":1,"kind":"start","at":0,"tenant":"default","data":{}}\n',
        encoding="utf-8",
    )
    assert fleet_metrics(tmp_path)["outcomes"]["abandoned"] == 1


def test_empty_directory_does_not_raise(tmp_path):
    assert fleet_metrics(tmp_path)["runs"] == 0
