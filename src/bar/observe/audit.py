"""Append-only audit log, written as it happens.

Written per event rather than at the end, because the runs worth investigating are
the ones that did not finish. A crash, a kill, a budget stop - all of them must leave
a complete record up to the moment they stopped.

The log is the replay format: every event carries what was decided and why, so a run
can be reconstructed without rerunning the model.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Event:
    run_id: str
    seq: int
    kind: str          # step | tool_call | tool_error | budget_stop | approval | finish
    at: float
    tenant: str = "default"
    data: dict[str, Any] = field(default_factory=dict)


class AuditLog:
    def __init__(self, path: str | Path = "runs", run_id: str | None = None,
                 tenant: str = "default") -> None:
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.tenant = tenant
        self.dir = Path(path)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / f"{self.run_id}.jsonl"
        self._seq = 0
        self.events: list[Event] = []

    def record(self, kind: str, **data: Any) -> Event:
        self._seq += 1
        event = Event(
            run_id=self.run_id, seq=self._seq, kind=kind,
            at=time.time(), tenant=self.tenant, data=data,
        )
        self.events.append(event)
        # Flushed immediately: a run that is killed must still have a readable trace.
        with self.file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(event), default=str) + "\n")
        return event

    @staticmethod
    def load(path: str | Path) -> list[Event]:
        """Rehydrate a run from disk for replay."""
        return [
            Event(**json.loads(line))
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def summary(self) -> dict:
        kinds: dict[str, int] = {}
        for e in self.events:
            kinds[e.kind] = kinds.get(e.kind, 0) + 1
        return {"run_id": self.run_id, "tenant": self.tenant,
                "events": len(self.events), "by_kind": kinds}
