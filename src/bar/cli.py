"""bar demo | replay"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, help="bounded-agent-runtime")
console = Console()


@app.command()
def demo(goal: str = "Find what the search tool says about hybrid retrieval") -> None:
    """Run a real LLM planner inside the runtime, against the demo toolset."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tests.toolset import build_registry  # the demo tools live with the tests

    from .budget import Budget
    from .config import get_settings
    from .runtime import Runtime
    from .runtime.planner import LLMPlanner

    s = get_settings()
    registry = build_registry()
    runtime = Runtime(
        registry,
        budget_factory=lambda: Budget(
            max_steps=s.max_steps,
            max_seconds=s.max_seconds,
            max_usd=s.max_usd,
            max_tool_calls=s.max_tool_calls,
            max_repeats=s.max_repeats,
        ),
        audit_dir=s.audit_dir,
    )
    result = runtime.run(goal, LLMPlanner(registry))

    console.print(f"[bold]{result.outcome.value}[/]  {result.reason}")
    if result.answer:
        console.print(result.answer)
    console.print(
        f"[dim]run={result.run_id} steps={result.steps} "
        f"usd={result.usd} seconds={result.seconds}[/]"
    )


@app.command()
def replay(run_id: str, audit_dir: str = "runs") -> None:
    """Reconstruct a run from its audit log, without rerunning the model."""
    from .observe.audit import AuditLog

    path = Path(audit_dir) / f"{run_id}.jsonl"
    if not path.exists():
        raise typer.BadParameter(f"no such run: {path}")

    table = Table("seq", "kind", "detail")
    for event in AuditLog.load(path):
        detail = ", ".join(f"{k}={str(v)[:60]}" for k, v in event.data.items())
        table.add_row(str(event.seq), event.kind, detail)
    console.print(table)


if __name__ == "__main__":
    app()
