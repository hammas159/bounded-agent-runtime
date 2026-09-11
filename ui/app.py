"""Ops console.

Built around the question an operator actually has - is this safe, and is it worth
running - rather than the one dashboards usually answer, which is how many requests
arrived. Escalations are shown separately from failures, because conflating them
hides the governance load. Cost per success is on the front page, because it is the
number that decides whether the system stays switched on.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bar.config import get_settings  # noqa: E402
from bar.observe.audit import AuditLog  # noqa: E402
from bar.observe.metrics import fleet_metrics  # noqa: E402

st.set_page_config(page_title="bounded-agent-runtime", page_icon="*", layout="wide")
settings = get_settings()
audit_dir = Path(settings.audit_dir)

st.title("bounded-agent-runtime")
st.caption("Limits the runtime enforces · every run auditable · every stop attributed")

m = fleet_metrics(audit_dir)

if not m.get("runs"):
    st.info(
        f"No runs yet in `{audit_dir}/`. Run `make demo`, or `make test` to "
        "generate runs from the containment suite."
    )
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Runs", m["runs"])
c2.metric("Success rate", f"{m['success_rate']:.0%}")
c3.metric(
    "Escalation rate",
    f"{m['escalation_rate']:.0%}",
    help="Runs that paused for human approval. Not failures.",
)
c4.metric("Cost per success", f"${m['usd_per_success']:.4f}" if m["usd_per_success"] else "—")

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
