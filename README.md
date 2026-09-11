# bounded-agent-runtime

[![ci](https://github.com/hammas159/bounded-agent-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/hammas159/bounded-agent-runtime/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.12-blue)
![license](https://img.shields.io/badge/license-MIT-green)

**An agent runtime whose limits the agent cannot influence — and a chaos suite that
proves it.**

Every job description asks for "safe" or "governed" agents. Almost every
implementation puts the limits in the prompt. This one puts them in the runtime,
then tries to break it on every push.

---

## The premise

An agent cannot be trusted to respect its own limits, because the thing being limited
is the thing doing the checking. So:

- every ceiling lives **outside** the agent loop
- it is checked **before** each step, not after
- it **raises** rather than returns — a returned error can be ignored by a caller,
  an exception unwinds the loop whether it wants to or not

```python
while True:
    budget.check()                    # before the step, so nothing runs over budget
    action = planner.next_action(...)  # a model, or a script
    budget.record_step(fingerprint)    # counts, and detects repetition
    result = registry.call(...)        # may raise ToolError or ApprovalRequired
```

## What is bounded

| Ceiling | Stops |
|---|---|
| `max_steps` | an agent that never emits `finish` |
| `max_seconds` | a hanging dependency |
| `max_usd` | steps that are individually cheap and collectively not |
| `max_tool_calls` | fan-out |
| `max_repeats` | **loop detection** — exact repetition of an action fingerprint |

Loop detection compares exact repetition rather than similarity. It is cheap, has no
false positives worth worrying about, and catches the failure that actually happens:
an agent re-issuing an identical call because the observation did not change. An
agent alternating between two actions is *not* flagged — that is a test.

Per-run `Budget` and per-tenant `Quota` are separate, on purpose. Without the second,
a caller exhausts a shared system by starting many individually well-behaved runs —
which is the failure that shows up in production.

## Risk is a property of the tool

Not a judgement the agent makes about its own plan. A tool declares its tier when it
is registered:

| Tier | Meaning |
|---|---|
| `READ` | observes; changes nothing |
| `WRITE` | changes state, reversibly |
| `EXTERNAL` | leaves the system |
| `IRREVERSIBLE` | cannot be undone — deletes, payments, notifications sent |

Anything above the autonomous ceiling **pauses the run intact** and waits for a
human. Not a failure — a gate. Approval lets the same run continue.

## The chaos suite is the project

Containment is asserted by replacing the agent with something guaranteed to
misbehave. No model, no network, no API key — so it runs in **milliseconds, in CI, on
every push**, rather than being demonstrated once in a screenshot.

| Scripted planner | Must result in |
|---|---|
| `NeverFinishes` | stopped at `max_steps` |
| `Repeats` | stopped by loop detection, **before** the step budget |
| `Expensive` | stopped at the cost ceiling |
| `Slow` | stopped by the wall clock |
| `WantsIrreversible` | paused for approval, **and the email is not sent** |
| `Hallucinates` | recovers and completes |
| `BrokenPlanner` | fails cleanly, trace intact |
| `Wellbehaved` | completes normally — containment must not break the happy path |

The test that matters asserts not that the runtime *reported* a stop, but that the
irreversible action **genuinely did not happen**, by checking the side effect it
would have produced:

```python
assert r.outcome is Outcome.NEEDS_APPROVAL
assert SIDE_EFFECTS == [], "an IRREVERSIBLE tool executed without approval"
```

**14 tests, all passing.** Two real bugs surfaced the first time the suite ran — both
of which would have survived code review:

- `AuditLog.record(kind, **data)` collided with callers passing `kind=` as payload.
- `ApprovalRequired` assigned `self.args`, shadowing `BaseException.args`, so
  `super().__init__()` silently replaced the tool arguments with the message tuple.
  The approval record was losing exactly the data a human needs in order to approve.

## Audit and replay

Events are flushed **per event, not at the end** — the runs worth investigating are
the ones that did not finish. A crash, a kill or a budget stop all leave a complete
record up to the moment they stopped, and the log is the replay format: a run can be
reconstructed without rerunning the model.

```
{"kind": "start",       "data": {"goal": "...", "limits": {...}}}
{"kind": "step",        "data": {"n": 1, "tool": "search", "reasoning": "..."}}
{"kind": "tool_error",  "data": {"tool": "always_fails", "error": "upstream unavailable"}}
{"kind": "approval",    "data": {"tool": "send_email", "tier": "IRREVERSIBLE", "args": {...}}}
{"kind": "budget_stop", "data": {"limit_kind": "loop", "limit": 3, "used": 3}}
{"kind": "finish",      "data": {"outcome": "budget_stop", "steps": 3, "usd": 0.003}}
```

## Quick start

```bash
make install
make test      # the containment suite — no model needed
make demo      # run a real agent against the toolset
```

## Layout

```
src/bar/
  budget/limits.py      Budget, BudgetExceeded — every ceiling
  tools/registry.py     Tool, RiskTier, the approval gate
  runtime/loop.py       the loop; Planner is a Protocol
  runtime/planner.py    the LLM planner — one of several possible planners
  observe/audit.py      append-only, flushed per event
  observe/quotas.py     per-tenant, across runs
tests/planners.py       scripted misbehaviour
tests/toolset.py        tools, including deliberately broken ones
tests/test_containment.py
```

## Requirements

[uv](https://docs.astral.sh/uv/). The containment suite needs nothing else — no GPU,
no database, no network. Running a real agent additionally needs an LLM backend
(Ollama locally, or an API key).

## License

MIT
