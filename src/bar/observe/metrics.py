"""Fleet metrics, read back from the audit logs.

Computed from the logs rather than accumulated in memory, so the numbers survive a
restart and can be recomputed for any time window. The set is chosen to answer the
question an operator actually has - "is this thing safe and is it worth running" -
rather than the question a dashboard usually answers, which is "how many requests".
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from .audit import AuditLog, Event


def _runs(audit_dir: str | Path) -> list[list[Event]]:
    directory = Path(audit_dir)
    if not directory.exists():
        return []
    out = []
    for path in sorted(directory.glob("*.jsonl")):
        try:
            events = AuditLog.load(path)
        except Exception:
            continue  # a run killed mid-write leaves a partial line; skip it
        if events:
            out.append(events)
    return out


def fleet_metrics(audit_dir: str | Path = "runs", tenant: str | None = None) -> dict:
    runs = _runs(audit_dir)
    if tenant:
        runs = [r for r in runs if r[0].tenant == tenant]
    if not runs:
        return {"runs": 0}

    outcomes: Counter[str] = Counter()
    stop_kinds: Counter[str] = Counter()
    total_usd = total_steps = 0.0
    tool_errors = 0
    approvals = 0

    for events in runs:
        finish = next((e for e in reversed(events) if e.kind == "finish"), None)
        if finish:
            outcomes[finish.data.get("outcome", "unknown")] += 1
            total_usd += float(finish.data.get("usd", 0) or 0)
            total_steps += float(finish.data.get("steps", 0) or 0)
        else:
            # No finish event means the process died without unwinding - itself a
            # finding, and invisible if you only count completed runs.
            outcomes["abandoned"] += 1

        for e in events:
            if e.kind == "budget_stop":
                stop_kinds[e.data.get("limit_kind", "unknown")] += 1
            elif e.kind == "tool_error":
                tool_errors += 1
            elif e.kind == "approval":
                approvals += 1

    n = len(runs)
    completed = outcomes.get("completed", 0)
    return {
        "runs": n,
        "success_rate": round(completed / n, 4),
        "budget_stop_rate": round(outcomes.get("budget_stop", 0) / n, 4),
        "escalation_rate": round(approvals / n, 4),
        "abandoned_rate": round(outcomes.get("abandoned", 0) / n, 4),
        "tool_error_rate": round(tool_errors / n, 4),
        "mean_steps": round(total_steps / n, 2),
        "mean_usd": round(total_usd / n, 6),
        "total_usd": round(total_usd, 4),
        # The number that decides whether the system stays switched on.
        "usd_per_success": round(total_usd / completed, 6) if completed else None,
        "outcomes": dict(outcomes),
        "stops_by_kind": dict(stop_kinds),
    }
