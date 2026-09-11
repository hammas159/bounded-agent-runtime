"""Tools, with risk tiers and an approval gate.

Two ideas the runtime depends on:

  Risk is a property of the tool, not of the prompt. A tool declares what it can do
  when it is registered, and the runtime decides whether that is allowed right now.

  Irreversible actions need a human. "Reversible" is not a judgement the agent makes
  about its own plan - it is declared once, by the person who wrote the tool.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class RiskTier(enum.IntEnum):
    """Ordered, so policy can be expressed as a single ceiling."""

    READ = 0        # observes; changes nothing
    WRITE = 1       # changes state, reversibly
    EXTERNAL = 2    # leaves the system: sends mail, calls a third party
    IRREVERSIBLE = 3  # cannot be undone: deletes, payments, notifications sent


class ApprovalRequired(RuntimeError):
    """Raised instead of acting, when a tool exceeds the autonomous ceiling."""

    def __init__(self, tool: str, tier: RiskTier, tool_args: dict) -> None:
        # Deliberately not `self.args`: BaseException.args is a built-in, and
        # super().__init__() below would overwrite it with the message tuple.
        self.tool, self.tier, self.tool_args = tool, tier, tool_args
        super().__init__(f"{tool} is {tier.name} and requires human approval")


class ToolError(RuntimeError):
    """A tool failed. Distinct from a budget or approval stop, and retryable."""


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]
    tier: RiskTier = RiskTier.READ
    # Rough cost per call, used by the budget. Estimated, not billed - the point is
    # that a runaway plan hits a ceiling, not that accounting is exact.
    usd_per_call: float = 0.0
    schema: dict = field(default_factory=dict)


@dataclass
class ToolRegistry:
    """Holds the tools and the policy that governs them."""

    tools: dict[str, Tool] = field(default_factory=dict)
    # Anything above this tier stops and asks. Default: act freely up to reversible
    # writes, escalate for anything that leaves the system or cannot be undone.
    autonomous_ceiling: RiskTier = RiskTier.WRITE

    def register(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise ValueError(f"tool {tool.name!r} already registered")
        self.tools[tool.name] = tool

    def describe(self) -> str:
        lines = []
        for t in sorted(self.tools.values(), key=lambda x: x.name):
            gate = "" if t.tier <= self.autonomous_ceiling else "  [requires approval]"
            lines.append(f"- {t.name}({', '.join(t.schema)}): {t.description}{gate}")
        return "\n".join(lines)

    def call(self, name: str, args: dict, *, approved: bool = False) -> Any:
        tool = self.tools.get(name)
        if tool is None:
            # Deliberately not a crash: a hallucinated tool name is an ordinary
            # failure the agent should be able to recover from.
            raise ToolError(f"no such tool {name!r}. Available: {', '.join(sorted(self.tools))}")

        if tool.tier > self.autonomous_ceiling and not approved:
            raise ApprovalRequired(name, tool.tier, args)

        try:
            return tool.fn(**args)
        except TypeError as exc:
            raise ToolError(f"{name} called with wrong arguments: {exc}") from exc
        except Exception as exc:
            raise ToolError(f"{name} failed: {exc}") from exc
