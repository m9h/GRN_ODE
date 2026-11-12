"""Collect completed GitHub partitions and audit complete model inventories.

This performs no numerical integration, workflow dispatch or retry. Failed and
timed-out computations retain their evidence and an explicit incomplete status.
Each workflow attempt and artifact has a separate immutable download directory.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.catalog_memory import write_json
from scripts import audit_breaking_shards as auditor


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GitHub:
    def __init__(self, repository):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("Specify one owner/repository")
        self.repository = repository

    def api(self, endpoint):
        result = subprocess.run(["gh", "api", f"repos/{self.repository}/{endpoint}"],
                                check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def download(self, artifact_id, output):
        with output.open("wb") as stream:
            subprocess.run(["gh", "api", f"repos/{self.repository}/actions/artifacts/{artifact_id}/zip"],
                           check=True, stdout=stream, stderr=subprocess.PIPE)


def pages(github, endpoint, field):
    rows, page = [], 1
    while True:
        result = github.api(f"{endpoint}?per_page=100&page={page}")
        rows.extend(result[field])
        if len(result[field]) < 100:
            return rows
        page += 1


def extract(archive, output):
    with zipfile.ZipFile(archive) as stream:
        names = set()
        for entry in stream.infolist():
            path = Path(entry.filename)
            if (path.is_absolute() or ".." in path.parts or entry.filename in names
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError("Unsafe or duplicate artifact member")
            names.add(entry.filename)
        stream.extractall(output)


def download_partition(github, artifact, job, run, network, index, directory):
    if artifact["expired"]:
        raise ValueError("Artifact has expired")
    if datetime.fromisoformat(artifact["created_at"]) < datetime.fromisoformat(job["started_at"]):
        raise ValueError("Artifact predates this job attempt")
    if artifact["workflow_run"]["head_sha"] != run["head_sha"] or artifact["workflow_run"]["id"] != run["id"]:
        raise ValueError("Artifact producer differs from the run")
    expected = artifact.get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
        raise ValueError("Artifact SHA-256 is required")
    destination = directory/f"artifact-{artifact['id']}"
    if not destination.exists():
        with tempfile.TemporaryDirectory(prefix="collect-", dir=directory) as temporary:
            staging = Path(temporary)/"artifact"
            staging.mkdir()
            archive = staging/"download.zip"
            github.download(artifact["id"], archive)
            if digest(archive) != expected.removeprefix("sha256:"):
                raise ValueError("Downloaded archive SHA-256 differs")
            extract(archive, staging/"evidence")
            staging.rename(destination)
    archive = destination/"download.zip"
    if digest(archive) != expected.removeprefix("sha256:"):
        raise ValueError("Saved archive SHA-256 differs")
    evidence = destination/"evidence"
    manifest = json.loads((evidence/"shard.json").read_text())
    if (manifest["network"] != network or manifest["shard_index"] != index
            or manifest["git_revision"] != run["head_sha"] or "finished_at" not in manifest
            or manifest["status"] == "running"):
        raise ValueError("Artifact does not describe this completed partition")
    return {"directory": str(evidence), "artifact_id": artifact["id"],
            "archive_sha256": expected, "manifest_sha256": digest(evidence/"shard.json"),
            "public_evidence_sha256": {str(p.relative_to(evidence)): digest(p)
                                       for p in sorted(evidence.rglob("*"))
                                       if p.is_file() and ".evidence" not in p.relative_to(evidence).parts
                                       and p.name != ".shard.lock"},
            "shard_index": index, "shard_count": manifest["shard_count"],
            "selected_coverage_complete": manifest["selected_coverage_complete"],
            "reported_passed_cases": manifest["selected_cases_passed"]}


def collect_run(github, run_id, root):
    run = github.api(f"actions/runs/{run_id}")
    if run["id"] != run_id or not re.fullmatch(r"[0-9a-f]{40}", run["head_sha"]):
        raise ValueError("Invalid run identity")
    directory = root/str(run_id)/f"attempt-{run['run_attempt']}"
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = pages(github, f"actions/runs/{run_id}/artifacts", "artifacts")
    by_name = {}
    for artifact in artifacts:
        if artifact["name"] in by_name:
            raise ValueError("Ambiguous artifact name within a workflow run")
        by_name[artifact["name"]] = artifact
    networks, errors = {}, []
    for job in pages(github, f"actions/runs/{run_id}/jobs", "jobs"):
        match = re.fullmatch(r"catalog-breaking-shards \((\d+), (\d+)\)", job["name"])
        if not match:
            continue
        network, index = map(int, match.groups())
        item = networks.setdefault(network, {"jobs": [], "partitions": []})
        item["jobs"].append({"index": index, "id": job["id"], "status": job["status"],
                             "conclusion": job["conclusion"]})
        if job["status"] != "completed":
            continue
        name = f"breaking-network-{network}-shard-{index}"
        try:
            item["partitions"].append(download_partition(
                github, by_name[name], job, run, network, index, directory))
        except Exception as error:
            errors.append({"network": network, "index": index, "error": f"{type(error).__name__}: {error}"})
    for network, item in networks.items():
        partitions = sorted(item["partitions"], key=lambda p: p["shard_index"])
        counts = {p["shard_count"] for p in partitions}
        complete = (len(counts) == 1 and len(partitions) == next(iter(counts))
                    and [p["shard_index"] for p in partitions] == list(range(len(partitions))))
        item.update(status="waiting_for_partitions", complete_case_coverage=False,
                    all_numerical_validations_passed=False)
        if not complete:
            continue
        item["needs_resume"] = [p["shard_index"] for p in partitions if not p["selected_coverage_complete"]]
        if item["needs_resume"]:
            item["status"] = "incomplete_execution"
            continue
        # An audit cache describes these immutable, checksummed archives. A new
        # artifact or auditor implementation requires a new full evidence audit.
        identity = {"partitions": partitions,
                    "auditor_sha256": digest(Path(auditor.__file__)),
                    "worker_source_sha256": {p.name: digest(p) for p in sorted((ROOT/"grn_memory").glob("*.py"))}}
        catalog = json.loads((ROOT/"models/catalog.json").read_text())["models"]
        model_id = next(e["biomodel_id"] for e in catalog if e["network"] == network)
        identity.update(model_sha256=digest(ROOT/"models"/(model_id+".xml")),
                        reference_sha256=digest(ROOT/"results/catalog-repeated"/(model_id+".json")))
        signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        audit_path = directory/f"network-{network}-audit.json"
        cache_path = directory/f"network-{network}-audit-source.json"
        try:
            cached = json.loads(cache_path.read_text()) if cache_path.exists() else {}
            if (cached.get("signature") == signature and audit_path.exists()
                    and cached.get("audit_sha256") == digest(audit_path)):
                result = json.loads(audit_path.read_text())
            else:
                result = auditor.audit([Path(p["directory"]) for p in partitions], network)
                write_json(audit_path, result)
                write_json(cache_path, {"signature": signature, "inputs": identity,
                                       "audit_sha256": digest(audit_path)})
            item.update(status="passed" if result["all_numerical_validations_passed"] else "numerical_disagreement",
                        complete_case_coverage=result["complete_case_coverage"],
                        all_numerical_validations_passed=result["all_numerical_validations_passed"],
                        cases=result["cases"], passed_cases=result["passed_cases"], audit=str(audit_path))
        except Exception as error:
            item.update(status="audit_error", error=f"{type(error).__name__}: {error}")
    result = {"purpose": __doc__, "run_id": run_id, "run_attempt": run["run_attempt"],
              "producer_revision": run["head_sha"], "github_status": run["status"],
              "github_conclusion": run["conclusion"], "networks": networks, "collection_errors": errors,
              "checked_at": datetime.now(timezone.utc).isoformat(), "integrations_performed": 0,
              "workflows_dispatched": 0, "catalog_completion_claimed": False}
    write_json(directory/"collection.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="m9h/GRN_ODE")
    parser.add_argument("--run", type=int, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=45.)
    args = parser.parse_args()
    if not 1 <= args.interval <= 60 or min(args.run) <= 0 or len(args.run) != len(set(args.run)):
        parser.error("Use distinct positive run IDs and an interval of 1–60 seconds")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    github, previous = GitHub(args.repository), None
    with (args.output/".collector.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            summaries = []
            for run_id in args.run:
                try:
                    result = collect_run(github, run_id, args.output)
                    summaries.append({"run": run_id, "github_status": result["github_status"],
                        "networks": {n: {k: v[k] for k in ("status", "complete_case_coverage", "all_numerical_validations_passed")}
                                     for n, v in result["networks"].items()},
                        "collection_errors": result["collection_errors"]})
                except Exception as error:
                    summaries.append({"run": run_id, "error": f"{type(error).__name__}: {error}"})
            write_json(args.output/"status.json", {"checked_at": datetime.now(timezone.utc).isoformat(), "runs": summaries})
            if summaries != previous:
                print(json.dumps(summaries), flush=True)
                previous = summaries
            if not args.watch:
                return int(any("error" in s or s.get("collection_errors")
                               or any(n["status"] == "audit_error" for n in s.get("networks", {}).values())
                               for s in summaries))
            time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
