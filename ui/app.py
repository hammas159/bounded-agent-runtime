"""Ops console.

Built around the question an operator actually has - is this safe, and is it worth
running - rather than the one dashboards usually answer, which is how many requests
arrived. Escalations are shown separately from failures, because conflating them
hides the governance load. Cost per success is on the front page, because it is the
number that decides whether the system stays switched on.

Two tabs: the fleet dashboard and replay (reads whatever is already in `audit_dir` -
`make demo` or `make test` populate it), and a "run live" tab that lets you trigger a
chaos-suite planner from the browser and watch it land in the same fleet view.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from bar.budget.limits import Budget  # noqa: E402
from bar.config import get_settings  # noqa: E402
from bar.observe.audit import AuditLog  # noqa: E402
from bar.observe.metrics import fleet_metrics  # noqa: E402
from bar.runtime.loop import Runtime  # noqa: E402
from tests.planners import (  # noqa: E402
    Expensive,
    Hallucinates,
    NeverFinishes,
    Repeats,
    Slow,
    WantsIrreversible,
    Wellbehaved,
)
from tests.toolset import SIDE_EFFECTS, build_registry  # noqa: E402

st.set_page_config(page_title="bounded-agent-runtime", page_icon="*", layout="wide")
settings = get_settings()
audit_dir = Path(settings.audit_dir)

st.title("bounded-agent-runtime")
st.caption("Limits the runtime enforces · every run auditable · every stop attributed")

tab_fleet, tab_live = st.tabs(["Fleet & replay", "Run a chaos scenario live"])

# ---- Tab 1: the original fleet dashboard + replay ----------------------------------

with tab_fleet:
    m = fleet_metrics(audit_dir)

    if not m.get("runs"):
        st.info(
            f"No runs yet in `{audit_dir}/`. Run `make demo`, `make test`, or use the "
            "'Run a chaos scenario live' tab to generate some."
        )
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Runs", m["runs"])
        c2.metric("Success rate", f"{m['success_rate']:.0%}")
        c3.metric(
            "Escalation rate",
            f"{m['escalation_rate']:.0%}",
            help="Runs that paused for human approval. Not failures.",
        )
        c4.metric(
            "Cost per success", f"${m['usd_per_success']:.4f}" if m["usd_per_success"] else "—"
        )

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Budget stops", f"{m['budget_stop_rate']:.0%}")
        c6.metric(
            "Abandoned",
            f"{m['abandoned_rate']:.0%}",
            help="No finish event - the process died without unwinding.",
        )
        c7.metric("Mean steps", m["mean_steps"])
        c8.metric("Total spend", f"${m['total_usd']:.4f}")

        left, right = st.columns(2)
        with left:
            st.subheader("Outcomes")
            st.bar_chart(pd.Series(m["outcomes"]))
        with right:
            st.subheader("Stops by ceiling")
            if m["stops_by_kind"]:
                st.bar_chart(pd.Series(m["stops_by_kind"]))
            else:
                st.caption("No run has hit a ceiling yet.")

        st.subheader("Runs")
        runs = sorted(audit_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        rows = []
        for path in runs[:200]:
            try:
                events = AuditLog.load(path)
            except Exception:
                continue
            finish = next((e for e in reversed(events) if e.kind == "finish"), None)
            start = events[0]
            rows.append(
                {
                    "run": path.stem,
                    "tenant": start.tenant,
                    "goal": str(start.data.get("goal", ""))[:60],
                    "outcome": finish.data.get("outcome", "—") if finish else "abandoned",
                    "steps": finish.data.get("steps") if finish else None,
                    "usd": finish.data.get("usd") if finish else None,
                    "seconds": finish.data.get("seconds") if finish else None,
                }
            )

        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        st.subheader("Replay")
        choice = st.selectbox("Run", [r["run"] for r in rows]) if rows else None
        if choice:
            for e in AuditLog.load(audit_dir / f"{choice}.jsonl"):
                colour = {
                    "budget_stop": "red",
                    "tool_error": "orange",
                    "approval": "violet",
                    "finish": "green",
                }.get(e.kind, "gray")
                st.markdown(f":{colour}[**{e.seq}. {e.kind}**]")
                st.json(e.data, expanded=False)

# ---- Tab 2: trigger a chaos-suite planner from the browser -------------------------

with tab_live:
    st.markdown(
        "The chaos suite replaces the agent with something guaranteed to misbehave, "
        "then checks the irreversible action **genuinely did not happen** - by "
        "reading the real side-effect list, not the runtime's self-report. Runs "
        "triggered here land in the same `audit_dir` as the tab above."
    )

    PLANNERS = {
        "Wellbehaved (control — should complete)": Wellbehaved,
        "NeverFinishes (runaway loop)": NeverFinishes,
        "Repeats (identical call forever)": Repeats,
        "Expensive (individually cheap, sums too high)": Expensive,
        "Slow (a dependency that hangs)": Slow,
        "WantsIrreversible (reaches for send_email)": WantsIrreversible,
        "Hallucinates (calls a tool that doesn't exist)": Hallucinates,
    }
    choice_name = st.selectbox("Misbehaving planner", list(PLANNERS.keys()))
    col1, col2 = st.columns(2)
    with col1:
        max_steps = st.slider("max_steps", 1, 20, 5)
        max_usd = st.slider("max_usd", 0.01, 0.50, 0.10)
    with col2:
        max_seconds = st.slider("max_seconds", 1.0, 30.0, 5.0)
        max_repeats = st.slider("max_repeats", 1, 5, 3)

    if st.button("Run this planner against the bounded runtime", type="primary"):
        registry = build_registry()
        runtime = Runtime(
            registry,
            budget_factory=lambda: Budget(
                max_steps=max_steps,
                max_seconds=max_seconds,
                max_usd=max_usd,
                max_repeats=max_repeats,
            ),
            audit_dir=str(audit_dir),
        )
        result = runtime.run("demo goal", PLANNERS[choice_name]())

        outcome_color = {"completed": "success", "budget_stop": "warning", "failed": "error"}
        getattr(st, outcome_color.get(result.outcome.value, "info"))(
            f"Outcome: **{result.outcome.value}** — {result.reason or '(no reason recorded)'}"
        )
        st.metric("Real side effects recorded", len(SIDE_EFFECTS))
        if choice_name.startswith("WantsIrreversible"):
            if len(SIDE_EFFECTS) == 0:
                st.success(
                    "The email was never sent — checked the actual side-effect list, "
                    "not just the runtime's claim."
                )
            else:
                st.error(f"CONTAINMENT FAILED: {SIDE_EFFECTS}")

        st.caption("Switch to the 'Fleet & replay' tab to see this run in context.")
