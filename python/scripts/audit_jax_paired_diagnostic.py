"""Audit a completed JAX diagnostic against its original failed-branch inventory.

This verifies archived provenance, coverage and comparison consistency. It does
not rerun trajectories or promote confirmed branches into recovered cases.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.catalog_memory import write_json
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import inspect_model
from grn_memory.paired_recovery import require, validate_comparison


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(directory, revision):
    report_path = directory/"report.json"
    report = json.loads(report_path.read_text())
    require(report["status"] == "completed", "Diagnostic is not complete")
    keys = ("model_id", "model_sha256", "jax_solver", "source_report_sha256", "source_fingerprint",
            "source_archive_sha256", "script_sha256", "implementation_sha256", "integration_requests",
            "comparison_settings", "grid", "versions")
    metadata = {k: report[k] for k in keys}
    # Newer diagnostics explicitly record the nonlinear root solver settings.
    for key in ("jax_root_finder", "jax_root_find_max_steps"):
        if key in report:
            metadata[key] = report[key]
    require(fingerprint(metadata) == report["fingerprint"], "Diagnostic fingerprint differs")
    require(report["comparison_settings"] == {"rtol": 2e-5, "atol": 1e-7}, "Acceptance differs")
    require(report["grid"] == {"duration": 300., "dt": .01, "post_reset_offset": 1e-5, "samples": 30001},
            "Observation grid differs")
    mid = report["model_id"]
    source = ROOT/"results/catalog-paired"/(mid+".json")
    original = json.loads(source.read_text())
    require(digest(source) == report["source_report_sha256"], "Original report hash differs")
    require(original["fingerprint"] == report["source_fingerprint"], "Original fingerprint differs")
    info = inspect_model(ROOT/"models"/(mid+".xml"))
    require(info["sha256"] == report["model_sha256"] == original["model_sha256"], "Model hash differs")
    archive = source.parent/original["branch_archive"]["file"]
    require(digest(archive) == report["source_archive_sha256"] == original["branch_archive"]["sha256"],
            "Original branch archive differs")
    with gzip.open(archive, "rt") as stream:
        inventory = {b["branch_id"]: b for line in stream if (b := json.loads(line))}
    failed = {bid for bid,b in inventory.items() if not b["passed"]}
    ids = report["selected_branch_ids"]
    require(len(ids) == len(set(ids)) == report["expected_branches"] == report["evaluated_branches"],
            "Diagnostic branch counts differ")
    require(report["original_branch_count"] == len(inventory), "Original branch count differs")
    require(set(ids) <= inventory.keys(), "Unknown diagnostic branch")
    if report["selection"] == "all originally failed branches":
        require(set(ids) == failed, "Failed-branch coverage is incomplete")
    elif report["selection"] != "explicit branches":
        raise ValueError("Unknown selection policy")
    for name, sha in {**report["implementation_sha256"], "scripts/diagnose_jax_paired.py": report["script_sha256"]}.items():
        if name.startswith("jaxkineticmodel/"):
            import importlib.util
            package_root = Path(importlib.util.find_spec("jaxkineticmodel").origin).parent
            actual = digest(package_root/Path(name).relative_to("jaxkineticmodel"))
        else:
            content = subprocess.check_output(["git", "show", f"{revision}:python/{name}"], cwd=ROOT)
            actual = hashlib.sha256(content).hexdigest()
        require(actual == sha, f"Source hash differs: {name}")
    pairs = ("jax_vs_roadrunner", "jax_refined_vs_roadrunner", "jax_vs_jax_refined",
             "roadrunner_vs_roadrunner_refined", "jax_refined_vs_roadrunner_refined")
    require(set(report["integration_requests"]) == {"jax", "jax_refined", "roadrunner", "roadrunner_refined"},
            "Diagnostic integration request inventory differs")
    statuses, files = Counter(), {}
    rows = {r["branch_id"]: r for r in report["branches"]}
    require(len(rows) == len(report["branches"]) and set(rows) == set(ids), "Report row coverage differs")
    for bid in ids:
        path = directory/(bid+".json")
        b = json.loads(path.read_text())
        require(b["branch_id"] == bid and b["fingerprint"] == report["fingerprint"], "Branch identity differs")
        for key in ("specification", "reset_trains"):
            require(b[key] == inventory[bid][key], f"Branch {key} differs")
        require(set(b["integrations"]) == set(report["integration_requests"]), "Integration inventory differs")
        completed = {e for e,v in b["integrations"].items() if v["completed"]}
        for engine,evidence in b["integrations"].items():
            require(evidence["request"] == report["integration_requests"][engine], "Integration request differs")
            if engine in completed:
                require(evidence["samples"] == 30001 and evidence["observables"] == len(info["observables"]),
                        "Incomplete integration observations")
        expected = {p for p in pairs if all(e in completed for e in p.split("_vs_"))}
        require(set(b["comparisons"]) == expected, "Comparison inventory differs")
        passes = [validate_comparison(c, info["observables"]) for c in b["comparisons"].values()]
        status = ("failed" if len(completed) != 4 else "confirmed" if all(passes) else "mismatch")
        require(b["status"] == rows[bid]["status"] == status, "Branch outcome differs")
        statuses[status] += 1
        files[path.name] = digest(path)
    require(statuses["confirmed"] == report["confirmed_branches"], "Confirmed-branch count differs")
    return {"purpose": __doc__, "source_revision": revision, "report_sha256": digest(report_path),
            "audit_script_sha256": digest(Path(__file__)), "model_id": mid,
            "complete_original_failed_branch_coverage": set(ids) == failed,
            "selected_branches": len(ids), "outcomes": dict(statuses),
            "all_selected_branches_confirmed": statuses["confirmed"] == len(ids),
            "branch_file_sha256": files}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args()
    result = audit(args.input, args.source_revision)
    write_json(args.input/"audit.json", result)
    print(json.dumps(result["outcomes"]))
