"""Per-tenant quotas.

Separate from Budget on purpose. A Budget bounds one run; a quota bounds a tenant
across runs. Without the second, a caller can exhaust a shared system by starting
many individually well-behaved runs - which is the failure that actually shows up
in production.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


class QuotaExceeded(RuntimeError):
    def __init__(self, tenant: str, kind: str, limit: float, used: float) -> None:
        self.tenant, self.kind = tenant, kind
        super().__init__(f"tenant {tenant!r} exceeded {kind} quota: {used:.4g} of {limit:.4g}")


@dataclass
class TenantQuota:
    max_runs_per_hour: int = 60
    max_usd_per_day: float = 5.0


@dataclass
class QuotaManager:
    quotas: dict[str, TenantQuota] = field(default_factory=dict)
    default: TenantQuota = field(default_factory=TenantQuota)
    _runs: dict[str, list[float]] = field(default_factory=dict)
    _spend: dict[str, list[tuple[float, float]]] = field(default_factory=dict)

    def _quota(self, tenant: str) -> TenantQuota:
        return self.quotas.get(tenant, self.default)

    def check_and_start(self, tenant: str) -> None:
        now = time.time()
        q = self._quota(tenant)

        runs = [t for t in self._runs.get(tenant, []) if now - t < 3600]
        if len(runs) >= q.max_runs_per_hour:
            raise QuotaExceeded(tenant, "runs/hour", q.max_runs_per_hour, len(runs))

        spend = [(t, u) for t, u in self._spend.get(tenant, []) if now - t < 86400]
        total = sum(u for _, u in spend)
        if total >= q.max_usd_per_day:
            raise QuotaExceeded(tenant, "usd/day", q.max_usd_per_day, total)

        runs.append(now)
        self._runs[tenant] = runs
        self._spend[tenant] = spend

    def record_spend(self, tenant: str, usd: float) -> None:
        self._spend.setdefault(tenant, []).append((time.time(), usd))

    def usage(self, tenant: str) -> dict:
        now = time.time()
        runs = [t for t in self._runs.get(tenant, []) if now - t < 3600]
        spend = sum(u for t, u in self._spend.get(tenant, []) if now - t < 86400)
        q = self._quota(tenant)
        return {
            "tenant": tenant,
            "runs_last_hour": len(runs), "max_runs_per_hour": q.max_runs_per_hour,
            "usd_today": round(spend, 4), "max_usd_per_day": q.max_usd_per_day,
        }
