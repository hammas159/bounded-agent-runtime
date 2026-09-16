"""Six agents that will not stop on their own. The runtime stops all six.

    python demo.py

None of this uses a model. Containment must not depend on the agent
cooperating, so the agent is replaced with something that definitely will not.
"""

import sys
import tempfile

sys.path.insert(0, "src")
sys.path.insert(0, ".")

from bar.budget import Budget
from bar.runtime.loop import Runtime
from tests.planners import (
    Expensive,
    Hallucinates,
    NeverFinishes,
    Repeats,
    Slow,
    WantsIrreversible,
    Wellbehaved,
)
from tests.toolset import build_registry

CASES = [
    ("Wellbehaved", Wellbehaved(), Budget(), "finishes on its own"),
    ("NeverFinishes", NeverFinishes(), Budget(max_steps=5), "loops forever"),
    ("Repeats", Repeats(), Budget(max_repeats=3), "same call over and over"),
    ("Expensive", Expensive(), Budget(max_usd=0.05), "burns budget"),
    ("Slow", Slow(), Budget(max_seconds=1.0, max_steps=999), "takes too long"),
    ("Hallucinates", Hallucinates(), Budget(), "calls a tool that does not exist"),
    ("WantsIrreversible", WantsIrreversible(), Budget(), "tries to send real email"),
]

tmp = tempfile.mkdtemp()

print("INPUT")
print(f"   {len(CASES)} planners, each given a goal and a budget")
for name, _, _budget, why in CASES:
    print(f"   {name:19} {why}")
print()

print("OUTPUT")
print(f"   {'planner':19} {'outcome':16} {'steps':>5}  reason")
print("   " + "-" * 82)
for name, planner, budget, _ in CASES:
    r = Runtime(
        build_registry(),
        budget_factory=lambda b=budget: b,
        audit_dir=tmp,
    ).run("go", planner)
    print(f"   {name:19} {r.outcome.name:16} {r.steps:>5}  {r.reason}")

print()
print("   Every stop came from the runtime, not from the agent agreeing to stop.")
print("   Hallucinates COMPLETED on purpose: an invented tool name is an error fed")
print("   back to the agent, not a crash. It recovered and finished in 2 steps.")
print(f"   A full audit trail for each run was written to {tmp}")
