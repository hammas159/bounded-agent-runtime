"""An LLM planner that satisfies the same Protocol as the scripted ones.

Kept deliberately small. The runtime does not become safer by having a cleverer
planner - it is safe because the planner cannot influence the budget. Swapping this
for a better model changes the success rate and nothing about containment.
"""

from __future__ import annotations

import json
import re

from ..config import get_settings
from ..llm import get_llm
from ..tools.registry import ToolRegistry
from .loop import Action

_JSON = re.compile(r"\{.*\}", re.S)

SYSTEM = """You are an agent that achieves a goal by calling tools.

Reply with ONE JSON object and nothing else:
{"reasoning": "<one short sentence>", "tool": "<tool name>", "args": {...}}

To finish, use the tool "finish" with {"answer": "<your answer>"}.
Use only the tools listed. If a tool returned an error, do something different -
repeating the same call will end the run."""


class LLMPlanner:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self.llm = get_llm(get_settings())

    def next_action(self, goal: str, history: list[dict]) -> Action:
        trace = (
            "\n".join(
                f"{i}. {h['action']}({json.dumps(h['args'], default=str)}) -> "
                f"{str(h['observation'])[:300]}"
                for i, h in enumerate(history, start=1)
            )
            or "(nothing yet)"
        )

        raw = self.llm.complete(
            f"GOAL: {goal}\n\nTOOLS:\n{self.registry.describe()}\n"
            f"- finish(answer): stop and return the answer\n\nSO FAR:\n{trace}\n\nJSON:",
            system=SYSTEM,
            max_tokens=400,
        )

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            m = _JSON.search(raw)
            if not m:
                # An unparseable plan is an ordinary failure. Returning `finish`
                # keeps the run terminating rather than spinning on bad output.
                return Action(
                    tool="finish",
                    args={"answer": raw.strip()[:500]},
                    reasoning="planner returned unparseable output",
                )
            try:
                parsed = json.loads(m.group())
            except json.JSONDecodeError:
                return Action(
                    tool="finish",
                    args={"answer": raw.strip()[:500]},
                    reasoning="planner returned unparseable output",
                )

        return Action(
            tool=str(parsed.get("tool", "finish")),
            args=parsed.get("args") or {},
            reasoning=str(parsed.get("reasoning", "")),
        )
