"""Restore one original case-control partition from a verified GitHub artifact.

The parent run, job attempt, artifact identity, original ZIP hash, unchanged
experiment and every completed cached array are checked before integration.
"""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import require
from grn_memory.catalog_memory import write_json
from grn_memory.scipy_case_partitions import (SOURCE_FILES, load_experiment, validate_metadata,
                                             verify_repository_sources, validate_cached_branches, selected_branches)
from scripts.collect_breaking_runs import GitHub as BaseGitHub, extract, pages


class GitHub(BaseGitHub):
    def api(self, endpoint):
        result = subprocess.run(["gh", "api", f"repos/{self.repository}/{endpoint}"], check=True,
                                capture_output=True, text=True, encoding="utf-8")
        return json.loads(result.stdout)


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def validate_artifact(artifact, run, job, expected_name):
    require(artifact["name"] == expected_name and artifact["expired"] is False
            and artifact["workflow_run"]["id"] == run["id"]
            and artifact["workflow_run"]["head_sha"] == run["head_sha"], "Parent artifact identity differs")
    require(run["status"] == "completed" and job["status"] == "completed"
            and datetime.fromisoformat(artifact["created_at"]) >= datetime.fromisoformat(job["started_at"]),
            "Parent artifact is not from this completed job attempt")
    require(isinstance(artifact.get("digest"), str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"]), "Original artifact SHA-256 is required")


def restore(args):
    require(args.run > 0, "A positive parent run ID is required")
    require(not args.output.exists() or not any(args.output.iterdir()), "Restore requires an empty output")
    plan, inventory, _, info, grid = load_experiment(args.inputs)
    selected_branches(inventory, plan["shard_count"], args.shard_index)
    github = GitHub(args.repository)
    run = github.api(f"actions/runs/{args.run}")
    require(run["id"] == args.run and run["path"] == ".github/workflows/scipy-case-controls.yml",
            "Parent workflow differs")
    jobs = pages(github, f"actions/runs/{args.run}/attempts/{run['run_attempt']}/jobs", "jobs")
    selected = [j for j in jobs if j["name"] == f"scipy-case-partition-{args.shard_index}"]
    require(len(selected) == 1, "One original parent partition job is required")
    job = selected[0]
    name = f"scipy-cases-{plan['model_id']}-partition-{args.shard_index}-attempt-{run['run_attempt']}"
    artifacts = pages(github, f"actions/runs/{args.run}/artifacts", "artifacts")
    matching = [a for a in artifacts if a["name"] == name]
    require(len(matching) == 1, "One unambiguous original artifact is required")
    artifact = matching[0]
    validate_artifact(artifact, run, job, name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="scipy-case-restore-", dir=args.output.parent) as temporary:
        staging = Path(temporary)
        archive = staging / "download.zip"
        github.download(artifact["id"], archive)
        require("sha256:" + digest(archive) == artifact["digest"], "Downloaded original ZIP digest differs")
        evidence = staging / "evidence"
        extract(archive, evidence)
        report = json.loads((evidence / "report.json").read_text())
        require(report["metadata"]["shard_index"] == args.shard_index
                and report["producer_revision"] == run["head_sha"], "Parent partition or producing revision differs")
        require(all(digest(evidence / n) == digest(args.inputs / n) for n in (*SOURCE_FILES, "execution-plan.json")),
                "Parent original input evidence differs")
        validate_metadata(report["metadata"], args.inputs / "execution-plan.json", plan, inventory, grid,
                          live_environment=True)
        verify_repository_sources(run["head_sha"], report["metadata"]["experiment"]["implementation_sha256"])
        verified = validate_cached_branches(evidence, report, inventory, grid, info)
        lineage = []
        if (evidence / "resume-source.json").exists():
            previous = json.loads((evidence / "resume-source.json").read_text())
            lineage = previous.pop("previous_sources", []) + [previous]
        provenance = {"run_id": args.run, "run_attempt": run["run_attempt"], "job_id": job["id"],
                      "producer_revision": run["head_sha"], "artifact_id": artifact["id"],
                      "archive_sha256": artifact["digest"], "archive_bytes": archive.stat().st_size,
                      "parent_report_sha256": digest(evidence / "report.json"),
                      "shard_index": args.shard_index, **verified, "previous_sources": lineage}
        write_json(evidence / "resume-source.json", provenance)
        shutil.copytree(evidence, args.output, dirs_exist_ok=True)
    return provenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="m9h/GRN_ODE")
    parser.add_argument("--run", required=True, type=int)
    parser.add_argument("--shard-index", required=True, type=int)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    result = restore(parser.parse_args())
    print(json.dumps({k: v for k, v in result.items() if k != "previous_sources"}))
