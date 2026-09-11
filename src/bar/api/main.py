"""HTTP surface and ops console backend."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..config import get_settings
from ..observe.audit import AuditLog
from ..observe.metrics import fleet_metrics

app = FastAPI(
    title="bounded-agent-runtime",
    version="0.1.0",
    description="An agent runtime that enforces its own limits.",
)


class RunRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=2000)
    tenant: str = "default"
    approvals: list[str] = Field(default_factory=list)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/metrics")
def metrics(tenant: str | None = None) -> dict:
    return fleet_metrics(get_settings().audit_dir, tenant=tenant)


@app.get("/runs/{run_id}")
def run_trace(run_id: str) -> dict:
    """Full trace. An operator who cannot see what the agent tried cannot govern it."""
    from pathlib import Path

    path = Path(get_settings().audit_dir) / f"{run_id}.jsonl"
    if not path.exists():
        raise HTTPException(404, f"no such run: {run_id}")
    return {"run_id": run_id, "events": [e.__dict__ for e in AuditLog.load(path)]}


@app.post("/run")
def start_run(req: RunRequest) -> dict:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from tests.toolset import build_registry

    from ..budget import Budget
    from ..observe.quotas import QuotaExceeded, QuotaManager
    from ..runtime import Runtime
    from ..runtime.planner import LLMPlanner

    s = get_settings()
    registry = build_registry()
    runtime = Runtime(
        registry,
        budget_factory=lambda: Budget(
            max_steps=s.max_steps, max_seconds=s.max_seconds, max_usd=s.max_usd,
            max_tool_calls=s.max_tool_calls, max_repeats=s.max_repeats,
        ),
        audit_dir=s.audit_dir,
        tenant=req.tenant,
        quotas=QuotaManager(),
    )
    try:
        result = runtime.run(req.goal, LLMPlanner(registry), approvals=set(req.approvals))
    except QuotaExceeded as exc:
        raise HTTPException(429, str(exc)) from exc
    return result.__dict__ | {"outcome": result.outcome.value}
