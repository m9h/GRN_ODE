"""Recompute the fixed missing-evidence inventory without changing numerical code.

Outputs are new calculations, not replacements for the historical report. They
must be collected with their lineage and pass the complete 215-branch case audit
before any selected case can be reported as recovered.
"""

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import require
from grn_memory.catalog_jax import source_hashes
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_runner import fingerprint
from grn_memory.scipy_breaking_recovery import digest, prepare_inventory
from scripts.audit_scipy_breaking import PACKAGES, SOURCES
from scripts.audit_scipy_breaking_cases import META_KEYS
from scripts.diagnose_scipy_breaking_controls import EXTRA_SOURCES, compute_branch

INPUT_NAMES = {
    "report.json", "inventory.json", "original-case-plan.json", "source-evidence.json",
    "source-branches.jsonl.gz", "source-branches-provenance.json",
    "reused-report.json", "reused-audit.json",
}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_selection(plan, preservation, report, reused):
    """Select by absent evidence, never by numerical outcome."""
    missing = {r["record_id"] for r in preservation["missing_branch_records"]}
    missing.update(name.split("-")[0] for name in preservation["missing_arrays"])
    imported = {r["record_id"] for r in reused["branches"]}
    require(plan["selected_branch_ids"] == sorted(missing - imported),
            "Recomputation must include every missing non-imported branch exactly once")
    require(plan["restore_from_release_branch_ids"] == sorted(missing & imported),
            "Imported branches must retain their published arrays")
    require(len(plan["selected_branch_ids"]) == 18
            and plan["expected_full_branches"] == report["expected_branches"] == 215
            and plan["expected_full_cases"] == len(report["selected_case_keys"]) == 2,
            "Original complete case scope differs")
    require(plan["full_case_recovery_claimed"] is False
            and report["case_recovery_claimed"] is False
            and report["full_model_coverage_claimed"] is False,
            "A branch producer cannot claim case or model recovery")


def load_inputs(directory, plan_sha256):
    directory = Path(directory)
    require(digest(directory / "recomputation-plan.json") == plan_sha256,
            "Recomputation plan hash differs")
    plan = read(directory / "recomputation-plan.json")
    require(set(plan["input_sha256"]) == INPUT_NAMES, "Input file inventory differs")
    for name, expected in plan["input_sha256"].items():
        require(digest(directory / name) == expected, f"Input checksum differs: {name}")
    require(plan["original_report_sha256"] == plan["input_sha256"]["report.json"],
            "Original report binding differs")
    require(digest(directory / "preservation-manifest.json") == plan["preservation_manifest_sha256"],
            "Preserved snapshot manifest differs")
    report = read(directory / "report.json")
    require(fingerprint({k: report[k] for k in META_KEYS}) == report["fingerprint"],
            "Original producer fingerprint differs")
    saved = read(directory / "inventory.json")
    inventory, model_path, info, grid = prepare_inventory(
        directory / "source-evidence.json", directory / "original-case-plan.json",
        saved["source_revision"], directory / "source-branches.jsonl.gz")
    require(saved == inventory and fingerprint(inventory) == report["inventory_sha256"],
            "Original controls, observation grid or inventory differ")
    require(info["sha256"] == report["model_sha256"], "Original SBML model differs")
    sources = source_hashes()
    sources.update({name: digest(ROOT / name) for name in (*SOURCES, *EXTRA_SOURCES)})
    require(sources == report["implementation_sha256"], "Numerical implementation differs")
    require({p: version(p) for p in PACKAGES} == report["versions"],
            "Numerical package versions differ")
    verify_selection(plan, read(directory / "preservation-manifest.json"), report,
                     read(directory / "reused-report.json"))
    require(set(plan["selected_branch_ids"]) <= inventory["branches"].keys(),
            "Requested branch is outside the original inventory")
    return plan, report, inventory, model_path, info, grid


def run(args):
    plan, report, inventory, model_path, info, grid = load_inputs(args.inputs, args.plan_sha256)
    if args.check_only:
        print(json.dumps({"selected_branches": len(plan["selected_branch_ids"]),
                          "full_case_inventory": 215, "selected_cases": 2,
                          "numerical_sources_identical": True}))
        return
    require(args.index is not None and 0 <= args.index < len(plan["selected_branch_ids"]),
            "Original replacement index is required")
    require(args.output is not None and not args.output.exists(),
            "Use a new output directory for each independent replacement calculation")
    bid = plan["selected_branch_ids"][args.index]
    old = next(b for b in report["branches"] if b["record_id"] == bid)
    args.output.mkdir(parents=True)
    lineage = {
        "purpose": __doc__, "created_at": datetime.now(timezone.utc).isoformat(),
        "plan_sha256": args.plan_sha256, "original_report_sha256": plan["original_report_sha256"],
        "index": args.index, "record_id": bid, "historical_record_sha256": old["sha256"],
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8").strip(),
        "wrapper_sha256": digest(Path(__file__)), "numerical_implementation_sha256": report["implementation_sha256"],
        "versions": report["versions"], "platform": platform.platform(),
        "machine": platform.machine(), "python": platform.python_version(),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "github_job": os.environ.get("GITHUB_JOB"),
        "byte_identical_restoration_claimed": False, "case_recovery_claimed": False,
        "full_model_coverage_claimed": False, "status": "running",
    }
    write_json(args.output / "lineage.json", lineage)
    row = compute_branch(bid, inventory["branches"][bid], args.output, report, grid, model_path, info)
    lineage.update(status="completed", branch=row, finished_at=datetime.now(timezone.utc).isoformat())
    write_json(args.output / "lineage.json", lineage)
    print(json.dumps(row))
    require(row["status"] == "confirmed", "Replacement branch is not numerically confirmed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--index", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-only", action="store_true")
    run(parser.parse_args())
