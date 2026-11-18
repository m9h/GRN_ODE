"""Fixed selection, runtime binding and terminal outcome preservation."""

import copy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scripts import run_ciliberto_full_diagnostics as runner

INPUTS = runner.ROOT / "results/catalog-breaking-ciliberto-full-diagnostics-20261118"
PLAN_SHA = "7a4f5cc4076de6d47a457220a8321d4b6849433c8eef599736c9c0a3f391f3c2"


def test_complete_real_selection_excludes_only_verified_original_failures():
    plan = runner.check(INPUTS, PLAN_SHA, check_runtime=False)
    rows = [row for part in plan["partitions"] for row in part["branches"]]
    assert len(rows) == len({row["record_id"] for row in rows}) == 260
    assert len(plan["original_failed_cases"]) == 74
    assert len(plan["previously_verified_failed_branches"]) == 10
    assert {len(part["branches"]) for part in plan["partitions"]} == {8, 9}
    assert plan["failure_kinds"] == {"integration_error": 249, "completed_mismatch": 11}
    assert plan["later_control_branches_required"] == 6859
    assert plan["full_case_audit_required"] is True


def test_plan_checksum_required():
    with pytest.raises(ValueError, match="checksum"):
        runner.check(INPUTS, "0" * 64, check_runtime=False)


@pytest.mark.parametrize("change", ["drop", "duplicate", "source_partition", "requests", "acceptance",
                                  "cases", "exclude_more", "later_controls", "case_claim", "model_claim"])
def test_plan_changes_rejected_even_when_outer_bytes_match(monkeypatch, change):
    read = runner.read
    plan = copy.deepcopy(read(INPUTS / "plan.json"))
    if change == "drop":
        plan["partitions"][0]["branches"].pop()
    elif change == "duplicate":
        plan["partitions"][0]["branches"][0] = plan["partitions"][1]["branches"][0]
    elif change == "source_partition":
        plan["partitions"][0]["branches"][0]["source_partition"] = 0
    elif change == "requests":
        plan["requests"]["rtol"] = 1e-5
    elif change == "acceptance":
        plan["acceptance"]["rtol"] = 1e-2
    elif change == "cases":
        plan["original_failed_cases"].pop()
    elif change == "exclude_more":
        plan["previously_verified_failed_branches"].append(plan["partitions"][0]["branches"][0]["record_id"])
    elif change == "later_controls":
        plan["later_control_branches_required"] = 0
    elif change == "case_claim":
        plan["case_recovery_claimed"] = True
    else:
        plan["full_model_coverage_claimed"] = True
    monkeypatch.setattr(runner, "read", lambda path: plan if Path(path) == INPUTS / "plan.json" else read(path))
    with pytest.raises(ValueError, match="execution plan differs"):
        runner.check(INPUTS, PLAN_SHA, check_runtime=False)


@pytest.mark.parametrize("change", ["inventory_checksum", "source_checksum", "wrong_source", "passing_source", "reused_mismatch"])
def test_source_or_reuse_changes_rejected(monkeypatch, change):
    digest, read = runner.digest, runner.read
    source = INPUTS / "source-partition-01.json"
    reuse = runner.SOURCE / "reused-recovery-audit.json"
    if change in ("inventory_checksum", "source_checksum"):
        changed = runner.SOURCE / "inventory.json" if change == "inventory_checksum" else source
        monkeypatch.setattr(runner, "digest", lambda path: "0" * 64 if Path(path) == changed else digest(path))
    else:
        changed = reuse if change == "reused_mismatch" else source
        value = copy.deepcopy(read(changed))
        if change == "wrong_source":
            value["original_report"]["network"] = 35
        elif change == "passing_source":
            value["failed_branches"][0]["passed"] = True
        else:
            value["branches"][0]["status"] = "mismatch"
        monkeypatch.setattr(runner, "read", lambda path: value if Path(path) == changed else read(path))
    with pytest.raises(ValueError):
        runner.check(INPUTS, PLAN_SHA, check_runtime=False)


def test_changed_runtime_rejected(monkeypatch):
    monkeypatch.setattr(runner, "runtime", lambda: {})
    with pytest.raises(ValueError, match="sources or package versions"):
        runner.check(INPUTS, PLAN_SHA)


@pytest.mark.parametrize("outcome", ["confirmed", "mismatch", "timeout", "nonzero", "audit_error"])
def test_worker_retains_every_outcome(tmp_path, monkeypatch, outcome):
    from scripts import audit_scipy_breaking
    row = {"record_id": "a" * 64, "source_partition": 1, "sample_count": 221001,
           "original_failure_kind": "integration_error"}
    plan = {"partitions": [{"branches": [row]}]}
    monkeypatch.setattr(runner, "runtime", lambda: {})
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *a, **k: "f" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")

    def run(command, **kwargs):
        assert command[command.index("--branch") + 1] == row["record_id"]
        assert command[command.index("--reference-rtol") + 1] == "1e-13"
        assert command[command.index("--rtol") + 1] == "1e-10"
        assert command[command.index("--evidence") + 1].endswith("source-partition-01.json")
        directory = Path(command[command.index("--output") + 1])
        directory.mkdir()
        (directory / "report.json").write_text("{}")
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return SimpleNamespace(returncode=3 if outcome == "nonzero" else 0)

    def audit(directory):
        if outcome == "audit_error":
            raise ValueError("Saved comparison changed")
        return {"all_selected_branches_confirmed": outcome == "confirmed"}

    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setattr(audit_scipy_breaking, "audit", audit)
    output = tmp_path / "result"
    code = runner.compute(INPUTS, plan, 0, output, 30)
    result = json.loads((output / "execution.json").read_text())
    assert result["run_id"] == "123" and result["run_attempt"] == "1"
    assert result["selected_branches"] == [row]
    assert result["case_recovery_claimed"] is result["full_model_coverage_claimed"] is False
    assert result["full_case_audit_required"] and result["later_control_branches_required"] == 6859
    assert (output / row["record_id"] / "report.json").exists()
    assert code == (0 if outcome == "confirmed" else 2)
    expected = {"confirmed": "confirmed", "mismatch": "numerical_failure", "timeout": "time_limit",
                "nonzero": "execution_or_audit_failure", "audit_error": "execution_or_audit_failure"}
    assert result["branches"][0]["status"] == expected[outcome]
    assert result["status"] == ("completed" if outcome in ("confirmed", "mismatch") else "incomplete")


def test_existing_output_is_never_overwritten(tmp_path):
    with pytest.raises(ValueError, match="new output"):
        runner.compute(INPUTS, {}, 0, tmp_path, 30)


def test_checkpoint_write_preserves_previous_json_on_serialization_failure(tmp_path):
    path = tmp_path / "execution.json"
    runner.write(path, {"status": "previous"})
    with pytest.raises(ValueError):
        runner.write(path, {"bad": float("nan")})
    assert json.loads(path.read_text()) == {"status": "previous"}
