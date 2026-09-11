"""Scripted planners for the chaos suite.

Each one models a specific way a real agent misbehaves. They are deterministic and
take microseconds, which is why containment can be asserted in CI on every push
rather than demonstrated once in a screenshot.
"""

from __future__ import annotations

from bar.runtime.loop import Action


class NeverFinishes:
    """Works forever without ever emitting `finish`. The commonest runaway."""

    def next_action(self, goal, history):
        return Action(tool="search", args={"q": f"query {len(history)}"})


class Repeats:
    """Re-issues the identical call because the observation never changes."""

    def next_action(self, goal, history):
        return Action(tool="search", args={"q": "same"})


class Expensive:
    """Each step is individually reasonable; the total is not."""

    def next_action(self, goal, history):
        return Action(tool="premium_model", args={"prompt": f"step {len(history)}"})


class Slow:
    def next_action(self, goal, history):
        return Action(tool="slow_api", args={"n": len(history)})


class WantsIrreversible:
    """Reaches for a tool that cannot be undone."""

    def next_action(self, goal, history):
        return Action(tool="send_email", args={"to": "board@example.com", "body": "oops"})


class Hallucinates:
    """Calls a tool that does not exist, then recovers and finishes."""

    def next_action(self, goal, history):
        if not history:
            return Action(tool="quantum_database", args={})
        return Action(tool="finish", args={"answer": "recovered"})


class Wellbehaved:
    def next_action(self, goal, history):
        if not history:
            return Action(tool="search", args={"q": goal})
        return Action(tool="finish", args={"answer": f"found: {history[-1]['observation']}"})


class BrokenPlanner:
    def next_action(self, goal, history):
        raise ValueError("planner exploded")


class SendsThenFinishes:
    """Performs the irreversible action once, then stops. Used to prove the approval
    gate is a gate and not a wall."""

    def next_action(self, goal, history):
        if not history:
            return Action(tool="send_email", args={"to": "board@example.com", "body": "ok"})
        return Action(tool="finish", args={"answer": "sent"})
