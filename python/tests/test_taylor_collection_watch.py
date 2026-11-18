"""Terminal workflow collection is distinct from complete scientific coverage."""

import json
import sys

import pytest

from scripts import collect_taylor_runs as collector


def partial(status="completed", errors=None):
    return {"run_id": 42, "model": 35, "github_status": status,
            "status": "incomplete_job_inventory", "complete_original_failure_coverage": False,
            "needs_continuation": [6], "missing_artifact_indices": [], "collection_errors": errors or []}


def watch(monkeypatch, tmp_path, states):
    monkeypatch.setattr(sys, "argv", ["collect_taylor_runs.py", "--run", "42", "--model", "35",
                                     "--output", str(tmp_path), "--watch", "--interval", "1"])
    calls, sleeps = [], []
    def collect(_github, run, model, output):
        calls.append((run, model))
        state = states.pop(0)
        if isinstance(state, Exception):
            raise state
        return state
    monkeypatch.setattr(collector, "collect_run", collect)
    def sleep(interval):
        sleeps.append(interval)
        assert len(sleeps) <= 3, "Watch continued after it should have stopped"
    monkeypatch.setattr(collector.time, "sleep", sleep)
    result = collector.main()
    return result, calls, sleeps, json.loads((tmp_path / "status.json").read_text())


def test_terminal_partial_run_exits_without_claiming_coverage(tmp_path, monkeypatch):
    code, calls, sleeps, saved = watch(monkeypatch, tmp_path, [partial()])
    assert code == 0 and calls == [(42, 35)] and not sleeps
    assert not saved["complete_original_failure_coverage"]
    assert saved["needs_continuation"] == [6]


def test_active_run_keeps_watching_until_terminal(tmp_path, monkeypatch):
    code, calls, sleeps, _ = watch(monkeypatch, tmp_path, [partial("in_progress"), partial()])
    assert code == 0 and calls == [(42, 35), (42, 35)] and sleeps == [1]


def test_transient_terminal_download_error_is_retried(tmp_path, monkeypatch):
    code, calls, sleeps, saved = watch(monkeypatch, tmp_path, [partial(errors=["download failed"]), partial()])
    assert code == 0 and len(calls) == 2 and sleeps == [1]
    assert saved["collection_errors"] == []


@pytest.mark.parametrize("error", [partial(errors=["wrong ZIP digest"]), RuntimeError("API unavailable")])
def test_persistent_failure_is_retained_and_stops_after_three_polls(tmp_path, monkeypatch, error):
    code, calls, sleeps, saved = watch(monkeypatch, tmp_path, [error, error, error])
    assert code == 1 and len(calls) == 3 and sleeps == [1, 1]
    assert "error" in saved or saved["collection_errors"]
