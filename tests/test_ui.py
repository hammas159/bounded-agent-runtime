"""Smoke tests for the Streamlit ops console (the `ui` dependency group).

Runs against an isolated AUDIT_DIR (set before any import touches
`get_settings()`, which is `lru_cache`d) so these tests never read or write the
real `runs/` directory that `make demo` / `make test` use.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

_TEST_AUDIT_DIR = Path(tempfile.mkdtemp(prefix="bar_ui_test_"))
os.environ["AUDIT_DIR"] = str(_TEST_AUDIT_DIR)

from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = str(Path(__file__).resolve().parent.parent / "ui" / "app.py")


def _app() -> AppTest:
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=15)
    assert not at.exception
    return at


def _select_planner(at: AppTest, name: str) -> AppTest:
    selectbox = next(sb for sb in at.selectbox if sb.label == "Misbehaving planner")
    selectbox.set_value(name).run(timeout=15)
    return at


def _click_run(at: AppTest) -> AppTest:
    button = next(b for b in at.button if "Run this planner" in b.label)
    button.click().run(timeout=15)
    return at


@pytest.fixture(scope="module", autouse=True)
def _clean_up_test_audit_dir():
    yield
    shutil.rmtree(_TEST_AUDIT_DIR, ignore_errors=True)


def test_app_loads_without_exceptions():
    _app()


def test_wellbehaved_planner_completes():
    at = _click_run(_select_planner(_app(), "Wellbehaved (control — should complete)"))
    assert not at.exception
    assert any("completed" in s.value for s in at.success)


def test_irreversible_action_is_actually_contained():
    """The real point of the project: check the side-effect list, not the runtime's
    self-report."""
    at = _click_run(_select_planner(_app(), "WantsIrreversible (reaches for send_email)"))
    assert not at.exception
    assert any("never sent" in s.value for s in at.success)


def test_never_finishes_planner_gets_budget_stopped():
    at = _click_run(_select_planner(_app(), "NeverFinishes (runaway loop)"))
    assert not at.exception
    assert any("budget_stop" in w.value for w in at.warning)


def test_fleet_tab_reflects_a_run_triggered_from_the_live_tab():
    at = _click_run(_app())
    assert not at.exception

    at2 = _app()
    assert any("Runs" in m.label for m in at2.metric)
