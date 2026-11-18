"""Verify the original Vilar partition-6 ZIP and reproduce its full-array audit.

This is a single complete diagnostic branch, not complete case recovery.
No network requests, Heyoka import or numerical integrations are performed.
"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from scripts.collect_taylor_runs import download_partition
from grn_memory.taylor_partitions import digest, require


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    selected = read(HERE / "selection.json")
    run, jobs, artifacts = [read(HERE / "api" / (name + ".json")) for name in ("run", "jobs", "artifacts")]
    require(jobs["total_count"] == len(jobs["jobs"]) and artifacts["total_count"] == len(artifacts["artifacts"]),
            "Incomplete API snapshot")
    require(run["id"] == selected["run_id"] and run["run_attempt"] == selected["run_attempt"]
            and run["head_sha"] == selected["producer_revision"] and run["status"] == "completed"
            and run["path"] == ".github/workflows/precision-checkpoints.yml", "Producer run differs")
    job = next(j for j in jobs["jobs"] if j["id"] == selected["job_id"])
    artifact = next(a for a in artifacts["artifacts"] if a["id"] == selected["artifact_id"])
    require(job["run_id"] == run["id"] and job["run_attempt"] == run["run_attempt"]
            and job["head_sha"] == run["head_sha"] and job["status"] == "completed"
            and job["name"] == "precision-model-35-partition-6"
            and artifact["name"] == job["name"], "Selected job or artifact differs")
    require(datetime.fromisoformat(job["started_at"]) <= datetime.fromisoformat(artifact["created_at"])
            <= datetime.fromisoformat(job["completed_at"]), "Artifact belongs to another execution")
    require(artifact["digest"] == "sha256:" + selected["archive_sha256"]
            and artifact["size_in_bytes"] == selected["archive_bytes"]
            and args.asset.stat().st_size == selected["archive_bytes"]
            and digest(args.asset) == selected["archive_sha256"], "Original ZIP bytes differ")

    class OfflineArtifact:
        def download(self, artifact_id, destination):
            require(artifact_id == selected["artifact_id"], "Unexpected artifact request")
            shutil.copyfile(args.asset, destination)

    args.output.mkdir(parents=True, exist_ok=False)
    row = download_partition(OfflineArtifact(), artifact, job, run, selected["model"], selected["index"], args.output)
    require(row["complete_arrays_audited"], "Complete arrays were not audited")
    fresh = read(Path(row["audit"]))
    require(fresh == read(HERE / "audit.json"), "Fresh complete diagnostic audit differs")
    require(row["report_sha256"] == digest(HERE / "report.json")
            and row["execution_sha256"] == digest(HERE / "execution.json"), "Published producer evidence differs")
    proof = {"fresh_audit_reproduced": True, "comparison": "Exact complete audit JSON equality",
             "archive_sha256": selected["archive_sha256"], "archive_bytes": selected["archive_bytes"],
             "audit_sha256": digest(Path(row["audit"])), "report_sha256": row["report_sha256"],
             "reproducer_sha256": digest(Path(__file__)), "model_id": fresh["model_id"], "partition_index": 6,
             "samples": fresh["summaries"][0]["samples"], "complete_arrays": 3,
             "status": fresh["summaries"][0]["status"], "numerical_integrations_performed": 0,
             "complete_original_failure_coverage": False, "case_recovery_claimed": False}
    (args.output / "reproduction-verification.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof))


if __name__ == "__main__":
    main()
