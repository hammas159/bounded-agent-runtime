"""Tools for the chaos suite, including deliberately broken ones.

`SIDE_EFFECTS` is the important part: the irreversible tool appends to it when it
runs. A test can then assert not merely that the runtime *said* it would stop, but
that the action genuinely did not happen.
"""

from __future__ import annotations

import time

from bar.tools.registry import RiskTier, Tool, ToolRegistry

SIDE_EFFECTS: list[str] = []


def build_registry(**overrides) -> ToolRegistry:
    SIDE_EFFECTS.clear()
    reg = ToolRegistry(**overrides)

    reg.register(
        Tool(
            "search",
            "Search the corpus",
            lambda q: f"results for {q}",
            RiskTier.READ,
            0.001,
            {"q": "str"},
        )
    )
    reg.register(
        Tool(
            "premium_model",
            "Expensive model call",
            lambda prompt: "answer",
            RiskTier.READ,
            0.05,
            {"prompt": "str"},
        )
    )
    reg.register(
        Tool(
            "slow_api",
            "A dependency that hangs",
            lambda n=0: (time.sleep(0.05), "slow result")[1],
            RiskTier.READ,
            0.0,
            {"n": "int"},
        )
    )
    reg.register(Tool("always_fails", "A dependency that is down", _broken, RiskTier.READ, 0.0, {}))
    reg.register(
        Tool(
            "write_record",
            "Update a record, reversibly",
            lambda key, value: f"{key}={value}",
            RiskTier.WRITE,
            0.0,
            {"key": "str", "value": "str"},
        )
    )
    reg.register(
        Tool(
            "send_email",
            "Send an email. Cannot be recalled.",
            _send_email,
            RiskTier.IRREVERSIBLE,
            0.0,
            {"to": "str", "body": "str"},
        )
    )
    return reg


def _broken():
    raise ConnectionError("upstream unavailable")


def _send_email(to: str, body: str) -> str:
    SIDE_EFFECTS.append(f"email->{to}")
    return "sent"
