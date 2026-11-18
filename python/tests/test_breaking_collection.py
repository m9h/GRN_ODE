"""A completed CI job or downloaded archive cannot substitute for model coverage."""

import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

import pytest

from scripts import collect_breaking_runs as collector


REVISION = "2e7327b0d273f4b33bdd8aa37601c1a497854a2a"


class FakeGitHub:
    def __init__(self, network=27):
        self.run = {"id": 123, "head_sha": REVISION, "run_attempt": 1,
                    "status": "completed", "conclusion": "success"}
        self.jobs, self.artifacts, self.archives, self.downloads = [], [], {}, []
        for index in range(4):
            source = collector.ROOT/f"results/catalog-breaking-linux-{network}/shard-{index}"
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in source.rglob("*"):
                    if path.is_file():
                        archive.writestr(str(path.relative_to(source)), path.read_bytes())
                archive.writestr(".evidence/checkpoint-marker", b"retained")
            self.archives[index+1] = stream.getvalue()
            self.artifacts.append({"id": index+1, "name": f"breaking-network-{network}-shard-{index}",
                "created_at": "2026-11-11T01:00:00Z", "expired": False,
                "digest": "sha256:"+hashlib.sha256(stream.getvalue()).hexdigest(),
                "workflow_run": {"id": 123, "head_sha": REVISION}})
            self.jobs.append({"id": index+100, "name": f"catalog-breaking-shards ({network}, {index})",
                "started_at": "2026-11-11T00:00:00Z", "status": "completed", "conclusion": "success"})

    def api(self, endpoint):
        if endpoint == "actions/runs/123":
            return self.run
        if endpoint.startswith("actions/runs/123/jobs?"):
            return {"jobs": self.jobs}
        if endpoint.startswith("actions/runs/123/artifacts?"):
            return {"artifacts": self.artifacts}
        raise AssertionError(endpoint)

    def download(self, artifact_id, output):
        self.downloads.append(artifact_id)
        output.write_bytes(self.archives[artifact_id])


@pytest.fixture(autouse=True)
def producer_sources(monkeypatch):
    source = collector.ROOT/"results/catalog-breaking-linux-27/shard-0"
    manifest = json.loads((source/"shard.json").read_text())
    report = json.loads((source/(manifest["model_id"]+".json")).read_text())
    hashes = {"grn_memory/"+name: value for name, value in report["implementation_sha256"].items()}
    hashes.update({"scripts/run_breaking_shard.py": manifest["runner_sha256"],
                   "grn_memory/breaking_shards.py": manifest["partition_source_sha256"]})
    def lookup(revision, name):
        assert revision == REVISION
        return hashes[name]
    # The live CLI smoke also verifies Git objects; fixtures work in shallow CI.
    monkeypatch.setattr(collector.auditor, "source_hash", lookup)


def test_complete_downloads_are_audited_and_unchanged_artifacts_are_reused(tmp_path, monkeypatch):
    github = FakeGitHub()
    real_audit = collector.auditor.audit
    calls = []
    def counted(paths, network):
        calls.append(network)
        return real_audit(paths, network)
    monkeypatch.setattr(collector.auditor, "audit", counted)
    first = collector.collect_run(github, 123, tmp_path)
    result = first["networks"][27]
    assert result["status"] == "passed" and result["cases"] == result["passed_cases"] == 22
    assert result["complete_case_coverage"] and result["all_numerical_validations_passed"]
    assert not first["catalog_completion_claimed"] and first["integrations_performed"] == first["workflows_dispatched"] == 0
    for part in result["partitions"]:
        assert (Path(part["directory"])/".evidence/checkpoint-marker").read_bytes() == b"retained"
    collector.collect_run(github, 123, tmp_path)
    assert github.downloads == [1, 2, 3, 4] and calls == [27]


def test_active_job_does_not_promote_its_existing_artifact(tmp_path):
    github = FakeGitHub(); github.jobs[0]["status"] = "in_progress"
    result = collector.collect_run(github, 123, tmp_path)
    assert github.downloads == [2, 3, 4]
    assert result["networks"][27]["status"] == "waiting_for_partitions"
    assert not result["networks"][27]["complete_case_coverage"]


@pytest.mark.parametrize("change,message", [
    ({"expired": True}, "expired"),
    ({"digest": "sha256:"+"0"*64}, "SHA-256 differs"),
    ({"created_at": "2026-11-10T00:00:00Z"}, "predates"),
    ({"workflow_run": {"id": 999, "head_sha": REVISION}}, "producer differs"),
])
def test_invalid_artifact_provenance_is_not_counted(tmp_path, change, message):
    github = FakeGitHub(); github.artifacts[0].update(change)
    result = collector.collect_run(github, 123, tmp_path)
    assert message in result["collection_errors"][0]["error"]
    assert len(result["networks"][27]["partitions"]) == 3
    assert not result["networks"][27]["all_numerical_validations_passed"]


def test_unsafe_archive_never_writes_outside_staging(tmp_path):
    github = FakeGitHub(); stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../escape", b"bad")
    github.archives[1] = stream.getvalue()
    github.artifacts[0]["digest"] = "sha256:"+hashlib.sha256(stream.getvalue()).hexdigest()
    result = collector.collect_run(github, 123, tmp_path)
    assert "Unsafe" in result["collection_errors"][0]["error"]
    assert not list(tmp_path.rglob("escape"))


def test_reruns_get_separate_download_directories(tmp_path):
    github = FakeGitHub(); first = collector.collect_run(github, 123, tmp_path)
    old = first["networks"][27]["partitions"][0]["directory"]
    github.run["run_attempt"] = 2
    second = collector.collect_run(github, 123, tmp_path)
    new = second["networks"][27]["partitions"][0]["directory"]
    assert old != new and Path(old).is_dir() and Path(new).is_dir()
    assert len(github.downloads) == 8


def test_changed_extracted_evidence_invalidates_the_audit_cache(tmp_path):
    github = FakeGitHub(); first = collector.collect_run(github, 123, tmp_path)
    directory = Path(first["networks"][27]["partitions"][0]["directory"])
    path = next((directory/"evidence").glob("*branches*.gz"))
    path.write_bytes(b"damaged")
    result = collector.collect_run(github, 123, tmp_path)["networks"][27]
    assert result["status"] == "audit_error" and not result["all_numerical_validations_passed"]


def test_timeout_is_saved_for_resume_without_a_model_pass(tmp_path):
    github = FakeGitHub()
    stream = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(github.archives[1])) as original, zipfile.ZipFile(stream, "w") as updated:
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == "shard.json":
                manifest = json.loads(data)
                manifest.update(status="incomplete", selected_coverage_complete=False, timed_out=True)
                data = json.dumps(manifest).encode()
            updated.writestr(item.filename, data)
    github.archives[1] = stream.getvalue()
    github.artifacts[0]["digest"] = "sha256:"+hashlib.sha256(stream.getvalue()).hexdigest()
    result = collector.collect_run(github, 123, tmp_path)["networks"][27]
    assert result["status"] == "incomplete_execution" and result["needs_resume"] == [0]
    assert not result["complete_case_coverage"] and not result["all_numerical_validations_passed"]


def test_finished_model_with_numerical_failures_remains_failed(tmp_path):
    github = FakeGitHub(26)
    result = collector.collect_run(github, 123, tmp_path)["networks"][26]
    assert result["status"] == "numerical_disagreement"
    assert result["complete_case_coverage"] and result["passed_cases"] == 116 and result["cases"] == 118
    assert not result["all_numerical_validations_passed"]


def watch_fixture(monkeypatch, tmp_path, runs, states):
    arguments = ["collect_breaking_runs.py", "--watch", "--interval", "1", "--output", str(tmp_path)]
    for run in runs:
        arguments += ["--run", str(run)]
    monkeypatch.setattr(sys, "argv", arguments)
    calls, sleeps = [], []
    def collect(_github, run, _output):
        calls.append(run)
        # Exhaustion means a terminal run was polled again unexpectedly.
        state = states[run].pop(0)
        if isinstance(state, Exception):
            raise state
        return state
    monkeypatch.setattr(collector, "collect_run", collect)
    def sleep(interval):
        sleeps.append(interval)
        assert len(sleeps) <= 3, "Collector did not exit"
    monkeypatch.setattr(collector.time, "sleep", sleep)
    return calls, sleeps


def partial_run(status="completed", errors=None):
    return {"github_status": status, "collection_errors": errors or [],
            "networks": {5: {"status": "waiting_for_partitions", "complete_case_coverage": False,
                             "all_numerical_validations_passed": False}}}


def test_watch_exits_on_terminal_partial_inventory_without_promoting_model(tmp_path, monkeypatch):
    calls, sleeps = watch_fixture(monkeypatch, tmp_path, [1], {1: [partial_run()]})
    assert collector.main() == 0
    assert calls == [1] and sleeps == []
    saved = json.loads((tmp_path / "status.json").read_text())
    assert not saved["runs"][0]["networks"]["5"]["complete_case_coverage"]


def test_watch_retains_completed_attempt_while_another_run_is_live(tmp_path, monkeypatch):
    calls, sleeps = watch_fixture(monkeypatch, tmp_path, [1, 2], {
        1: [partial_run()], 2: [partial_run("in_progress"), partial_run()]})
    assert collector.main() == 0
    assert calls == [1, 2, 2] and sleeps == [1]


def test_watch_retries_transient_terminal_download_error(tmp_path, monkeypatch):
    calls, sleeps = watch_fixture(monkeypatch, tmp_path, [1], {
        1: [partial_run(errors=[{"error": "temporary download failure"}]), partial_run()]})
    assert collector.main() == 0
    assert calls == [1, 1] and sleeps == [1]


@pytest.mark.parametrize("error", [partial_run(errors=[{"error": "bad ZIP hash"}]),
                                  RuntimeError("API unavailable")])
def test_watch_preserves_error_and_stops_after_three_failed_polls(tmp_path, monkeypatch, error):
    calls, sleeps = watch_fixture(monkeypatch, tmp_path, [1], {1: [error, error, error]})
    assert collector.main() == 1
    assert calls == [1, 1, 1] and sleeps == [1, 1]
    saved = json.loads((tmp_path / "status.json").read_text())
    assert collector.has_collection_error(saved["runs"])
