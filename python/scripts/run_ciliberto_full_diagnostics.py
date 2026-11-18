"""Execute the fixed first stage of the complete Ciliberto failure plan.

All 260 remaining original failures receive four complete trajectories. The
6,859 later controls and full 74-case audit remain required, regardless of
diagnostic outcomes. Numerical integration and array auditing are unchanged.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODEL = "BIOMD0000000697"
SOURCE = ROOT / "results/catalog-breaking-ciliberto-full-inventory-20261118"
INVENTORY_SHA = "6edb21883885dffc7c694a326d89e11887de9c4847f2f9dcb1059d11b4ef3ff0"
SCHEDULE_SHA = "eb28b288b8a2eeba859ab25f28075f839ea02e28ac551e7437a0264d789a525e"
PARTITIONS = 32
REQUESTS = {"rtol": 1e-10, "atol": 1e-12, "reference_rtol": 1e-13, "reference_atol": 1e-15}
PACKAGES = ("jax", "jaxlib", "jaxkineticmodel", "diffrax", "equinox", "scipy",
            "numpy", "pandas", "libroadrunner", "python-libsbml")
NUMERICAL_FILES = ("scripts/diagnose_scipy_breaking.py", "scripts/audit_scipy_breaking.py",
                   "grn_memory/scipy_reference.py", "grn_memory/jax_protocols.py",
                   "grn_memory/catalog_repeated.py", "grn_memory/catalog_breaking.py",
                   "grn_memory/native_protocols.py", "grn_memory/catalog_validation.py",
                   "pyproject.toml", "uv.lock")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def runtime():
    from grn_memory.catalog_jax import source_hashes
    return {"source_hashes": {**source_hashes(), **{name: digest(ROOT / name) for name in NUMERICAL_FILES}},
            "versions": {name: version(name) for name in PACKAGES}}


def source_selection(directory):
    from types import SimpleNamespace
    from scripts.diagnose_scipy_breaking import requests
    from scripts.plan_ciliberto_full_computation import make_plan
    require(digest(SOURCE / "inventory.json") == INVENTORY_SHA
            and digest(SOURCE / "computation-plan.json") == SCHEDULE_SHA,
            "Complete fixed source inventory or schedule checksum differs")
    inventory = read(SOURCE / "inventory.json")
    schedule = read(SOURCE / "computation-plan.json")
    require(schedule == make_plan(inventory, INVENTORY_SHA), "Full computation schedule differs")
    require(requests(SimpleNamespace(**REQUESTS)) == inventory["requests"]
            and inventory["acceptance"] == {"rtol": 2e-5, "atol": 1e-7}, "Numerical requests differ")
    original_root = ROOT / "results/catalog-breaking-linux-28"
    original_audit = read(original_root / "audit.json")
    require(digest(original_root / "audit.json") == inventory["original_audit_sha256"]
            and original_audit["cases"] == 622 and original_audit["passed_cases"] == 548
            and sorted(inventory["cases"]) == sorted(k for k, v in original_audit["case_summaries"].items()
                                                     if v["status"] != "passed"), "Original case scope differs")
    require(digest(ROOT / "models" / (MODEL + ".xml")) == inventory["model_sha256"], "SBML model differs")
    require(len(inventory["source_partitions"]) == 16, "All original source partitions are required")
    entries, failed = [], {}
    for index, entry in enumerate(inventory["source_partitions"]):
        require(entry["index"] == index and entry["file"] == f"source-partition-{index:02d}.json",
                "Source partition selection differs")
        path = directory / entry["file"]
        require(not path.is_symlink() and digest(path) == entry["sha256"], "Source capture checksum differs")
        evidence = read(path)
        original = evidence["original_report"]
        original_path = original_root / f"shard-{index}" / (MODEL + ".json")
        require(original == read(original_path) and original["network"] == 28 and original["biomodel_id"] == MODEL
                and evidence["original_report_sha256"] == entry["original_report_sha256"] == digest(original_path),
                "Original source report differs")
        require(len(evidence["failed_branches"]) == entry["failed_branches"], "Source failure count differs")
        entries.append({"source_partition": index, "file": entry["file"], "sha256": entry["sha256"],
                        "original_report_sha256": entry["original_report_sha256"], "failed_branches": entry["failed_branches"]})
        for branch in evidence["failed_branches"]:
            bid = branch["record_id"]
            require(branch["passed"] is False and bid not in failed
                    and inventory["branches"].get(bid) == branch["specification"], "Original failed branch selection differs")
            failed[bid] = {"record_id": bid, "source_partition": index, "sample_count": branch["sample_count"],
                           "original_failure_kind": "integration_error" if "error" in branch else "completed_mismatch"}
    require(len(failed) == 270, "All original failed branches are required")
    recovery = read(SOURCE / "reused-recovery-audit.json")
    require(digest(SOURCE / "reused-recovery-audit.json") == inventory["reused_audit_sha256"]
            and recovery["report_sha256"] == inventory["reused_report_sha256"]
            and recovery["complete_selected_control_inventory"] is True and recovery["baseline_passed"] is True
            and recovery["recovered_selected_cases"] == recovery["selected_cases"] == 2,
            "Previously verified complete-case recovery differs")
    reused = inventory["reusable_verified_branches"]
    require(len(recovery["branches"]) == len(reused) == 215
            and {b["record_id"] for b in recovery["branches"]} == set(reused), "Previously verified branch inventory differs")
    for branch in recovery["branches"]:
        require(branch["status"] == "confirmed" and branch["record_sha256"] == reused[branch["record_id"]]["sha256"],
                "Previously verified branch result differs")
    excluded = sorted(failed.keys() & reused.keys())
    selected = sorted(failed.keys() - reused.keys())
    require(len(excluded) == 10 and len(selected) == 260
            and selected == schedule["stage_1"]["branches"], "Complete remaining failure selection differs")
    partitions = [{"index": part["index"], "branches": [failed[bid] for bid in part["branch_ids"]]}
                  for part in schedule["stage_1"]["partitions"]]
    require(len(partitions) == PARTITIONS and [p["index"] for p in partitions] == list(range(PARTITIONS)),
            "Fixed partition inventory differs")
    return {"schema_version": 1, "network": 28, "model_id": MODEL,
            "source_inventory_sha256": INVENTORY_SHA, "full_computation_plan_sha256": SCHEDULE_SHA,
            "original_audit_sha256": inventory["original_audit_sha256"], "model_sha256": inventory["model_sha256"],
            "original_cases": 622, "original_passed_cases": 548, "original_failed_cases": sorted(inventory["cases"]),
            "original_failed_branches": 270, "previously_verified_failed_branches": excluded,
            "reused_audit_sha256": inventory["reused_audit_sha256"], "source_partitions": entries,
            "expected_branches": 260, "partition_count": PARTITIONS, "partitions": partitions,
            "failure_kinds": dict(Counter(failed[bid]["original_failure_kind"] for bid in selected)),
            "requests": REQUESTS, "acceptance": {"rtol": 2e-5, "atol": 1e-7},
            "later_control_branches_required": 6859, "full_case_audit_required": True,
            "numerical_integrations_performed_during_capture": 0,
            "case_recovery_claimed": False, "full_model_coverage_claimed": False}


def capture(output):
    require(not output.exists(), "Use a new capture directory")
    selection = source_selection(SOURCE)
    output.mkdir(parents=True)
    for entry in selection["source_partitions"]:
        shutil.copyfile(SOURCE / entry["file"], output / entry["file"])
    require(selection == source_selection(output), "Copied selection differs")
    plan = {**selection, "runtime": runtime()}
    write(output / "plan.json", plan)
    print(json.dumps({"branches": 260, "partitions": PARTITIONS, "plan_sha256": digest(output / "plan.json")}), flush=True)


def check(inputs, expected_sha, *, check_runtime=True):
    require(digest(inputs / "plan.json") == expected_sha, "Fixed execution plan checksum differs")
    plan = read(inputs / "plan.json")
    require(plan == {**source_selection(inputs), "runtime": plan["runtime"]}, "Complete execution plan differs")
    if check_runtime:
        require(plan["runtime"] == runtime(), "Numerical sources or package versions differ")
        from scripts.diagnose_scipy_breaking import prepare
        for entry in plan["source_partitions"]:
            prepare(inputs / entry["file"])
    return plan


# The bounded execution function is copied from the tested Rohwer wrapper;
# its child numerical producer and full-array auditor remain unchanged.


def compute(inputs, plan, index, output, budget):
    require(type(index) is int and 0 <= index < PARTITIONS, 'Invalid partition index')
    require(0 < budget <= 19800, 'Invalid execution budget')
    require(not output.exists(), 'Use a new output; continuation requires separately verified evidence')
    output.mkdir(parents=True)
    selected = plan['partitions'][index]['branches']
    result = {'model_id': MODEL, 'plan_sha256': digest(inputs/'plan.json'), 'partition_index': index,
              'expected_branches': len(selected), 'selected_branches': selected,
              'producer_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'run_id': os.environ.get('GITHUB_RUN_ID'), 'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
              'runner_sha256': digest(Path(__file__)), 'runtime': runtime(),
              'status': 'running', 'branches': [], 'case_recovery_claimed': False,
              'full_model_coverage_claimed': False, 'full_case_audit_required': True,
              'later_control_branches_required': 6859,
              'started_at': datetime.now(timezone.utc).isoformat()}
    write(output/'execution.json', result)
    deadline = time.monotonic()+budget
    for row in selected:
        if time.monotonic() >= deadline:
            break
        bid, source_index = row['record_id'], row['source_partition']
        directory = output/bid
        command = [sys.executable, str(ROOT/'scripts/diagnose_scipy_breaking.py'),
                   '--evidence', str((inputs/f'source-partition-{source_index:02d}.json').resolve()),
                   '--branch', bid, '--output', str(directory.resolve())]
        for key, value in REQUESTS.items():
            command.extend(['--'+key.replace('_', '-'), str(value)])
        item = {**row, 'status': 'running'}
        result['branches'].append(item)
        write(output/'execution.json', result)
        try:
            completed = subprocess.run(command, cwd=ROOT, timeout=max(.001, deadline-time.monotonic()))
            require(completed.returncode == 0, f'Diagnostic process exited {completed.returncode}')
            from scripts.audit_scipy_breaking import audit
            checked = audit(directory)
            write(directory/'audit.json', checked)
            item.update(status='confirmed' if checked['all_selected_branches_confirmed'] else 'numerical_failure',
                        audit_sha256=digest(directory/'audit.json'), report_sha256=digest(directory/'report.json'))
        except subprocess.TimeoutExpired:
            item.update(status='time_limit', error='Execution budget exhausted; partial files retained')
        except Exception as error:
            item.update(status='execution_or_audit_failure', error=f'{type(error).__name__}: {error}')
        write(output/'execution.json', result)
        print(json.dumps(item), flush=True)
    result.update(status='completed' if len(result['branches']) == len(selected)
                  and all(b['status'] in ('confirmed', 'numerical_failure') for b in result['branches']) else 'incomplete',
                  confirmed_branches=sum(b['status'] == 'confirmed' for b in result['branches']),
                  finished_at=datetime.now(timezone.utc).isoformat())
    write(output/'execution.json', result)
    return 0 if result['confirmed_branches'] == len(selected) else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["capture", "check", "compute"])
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--index", type=int)
    parser.add_argument("--budget", type=float, default=19200)
    args = parser.parse_args()
    if args.operation == "capture":
        require(args.output is not None, "Capture output is required")
        capture(args.output)
    else:
        require(args.inputs is not None and args.plan_sha256 is not None, "Pinned inputs are required")
        plan = check(args.inputs, args.plan_sha256)
        if args.operation == "compute":
            require(args.output is not None, "Compute output is required")
            sys.exit(compute(args.inputs, plan, args.index, args.output, args.budget))
        print(json.dumps({"all_260_remaining_original_failures_selected": True, "numerical_integrations_performed": 0}))
