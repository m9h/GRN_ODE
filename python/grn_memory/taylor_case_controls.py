"""Complete paired-case controls using the unchanged precision integrators.

The failed-branch batch and this complementary control batch together cover
every arm of each declared case. Only an audit of the full saved arrays can
recover a case; the short untreated baseline cannot replace a 300-unit sham.
"""

from copy import deepcopy
import fcntl
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import subprocess

import numpy as np

from . import taylor_partitions as partitions
from .catalog_paired import WINDOWS
from .catalog_repeated import summarize
from .native_protocols import ResetTrain, sample_times
from .paired_scores import classification_key, response_score
from .taylor_checkpoints import signature
from .taylor_partitions import ROOT, REQUESTS, assess, digest, load_trace, require, verify_report_identity
from scripts.recover_scipy_paired_cases import original_context

ORIGINAL_REVISION = "70a3afad61357e94873ff62a7300c099b4c7ae3e"
SOURCES = (*partitions.SOURCES, "grn_memory/taylor_case_controls.py",
           "grn_memory/catalog_paired.py", "grn_memory/catalog_repeated.py",
           "grn_memory/catalog_runner.py", "grn_memory/paired_recovery.py",
           "grn_memory/paired_scores.py", "grn_memory/analysis.py",
           "scripts/recover_scipy_paired_cases.py", "scripts/run_taylor_case_control.py",
           "grn_memory/taylor_control_resume.py", "scripts/run_taylor_control_ci.py")


def make_plan(model, cases, source_revision=ORIGINAL_REVISION):
    require(type(model) is int and model > 0, "Positive model number required")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", source_revision)), "Exact original revision required")
    require(bool(cases) and len(cases) == len(set(cases)), "Distinct explicit cases required")
    mid = f"BIOMD{model:010d}"
    original, candidates, branches, info, source = original_context(
        mid, ROOT / "results/catalog-paired", source_revision)
    require(all(key in candidates and original["cases"][key]["status"] != "passed" for key in cases),
            "Only original failed cases may be selected")
    selected = {key: {**deepcopy(candidates[key]), "branches": original["cases"][key]["branches"]}
                for key in sorted(cases)}
    required = sorted({bid for case in selected.values() for bid in case["branches"].values()})
    failed = sorted(bid for bid, row in branches.items() if not row["passed"])
    controls = sorted(set(required) - set(failed))
    grid = sample_times(300., .01, [ResetTrain(t, t+50., {}) for t in (50., 150., 200.)],
                        post_reset_offset=1e-5)
    return {"schema": 1, "scope": "paired-case-controls", "model_id": mid,
            "model_sha256": info["sha256"], "original_source_revision": source_revision,
            "source_report_sha256": digest(source), "source_archive_sha256": original["branch_archive"]["sha256"],
            "source_fingerprint": original["fingerprint"], "cases": selected,
            "required_branch_ids": required, "control_branch_ids": controls,
            "existing_failed_partition_indices": {bid: failed.index(bid)+1 for bid in required if bid in failed},
            "existing_failed_partition_count": len(failed)+1,
            "branches": {bid: {"specification": branches[bid]["specification"],
                               "reset_trains": branches[bid]["reset_trains"]} for bid in required},
            "grid": {"duration": 300., "dt": .01, "post_reset_offset": 1e-5, "samples": len(grid),
                     "sha256": hashlib.sha256(grid.tobytes()).hexdigest()},
            "requests": deepcopy(REQUESTS), "acceptance": dict(partitions.ACCEPTANCE),
            "case_recovery_claimed": False}


def validate_plan(plan):
    model = int(plan["model_id"].removeprefix("BIOMD"))
    expected = make_plan(model, list(plan["cases"]), plan["original_source_revision"])
    require(plan == expected, "Case plan differs from the complete original evidence")
    return model


def problem(plan, index, count):
    model = validate_plan(plan)
    ids = plan["control_branch_ids"]
    require(type(count) is int and count == len(ids) and type(index) is int and 0 <= index < count,
            "Partition inventory must cover every selected control")
    # Reuse the existing full failure inventory and byte-identical numerical code.
    path, info, _, core, _ = partitions.problem(model, 0, plan["existing_failed_partition_count"])
    times = sample_times(300., .01, [ResetTrain(t, t+50., {}) for t in (50., 150., 200.)],
                         post_reset_offset=1e-5)
    core.update(schema=2, scope="paired-case-controls", case_plan_sha256=signature(plan),
                selected_cases=sorted(plan["cases"]), required_branch_ids=plan["required_branch_ids"],
                control_branch_ids=ids, implementation_sha256={name: digest(ROOT/name) for name in SOURCES})
    bid = ids[index]
    selection = {"index": index, "count": count, "branch_id": bid,
                 "reset_trains": plan["branches"][bid]["reset_trains"], "samples": len(times),
                 "times_sha256": hashlib.sha256(times.tobytes()).hexdigest()}
    return path, info, times, core, selection


@lru_cache(maxsize=64)
def verify_committed_sources(revision, sources):
    require(bool(re.fullmatch(r"[0-9a-f]{40}", revision)), "Exact producer revision required")
    for name, expected in sources:
        result = subprocess.run(["git", "show", f"{revision}:python/{name}"], cwd=ROOT, capture_output=True)
        require(result.returncode == 0 and hashlib.sha256(result.stdout).hexdigest() == expected,
                f"Producer source differs: {name}")


def verify_attempts(report):
    require(bool(report["attempts"]), "Producer attempts are missing")
    for attempt in report["attempts"]:
        require(attempt["implementation_files_differing_from_revision"] == [], "Uncommitted numerical source")
        verify_committed_sources(attempt["source_revision"], tuple(sorted(report["core"]["implementation_sha256"].items())))


def run_partition(plan, index, count, output, *, resume=False, max_seconds=14400.):
    require(np.isfinite(max_seconds) and max_seconds > 0, "Positive finite wall budget required")
    path, info, times, core, selection = problem(plan, index, count)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    verify_committed_sources(revision, tuple(sorted(core["implementation_sha256"].items())))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".runner.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if resume:
            validate_evidence(output, plan, index, count, resume=True)
        return partitions._run(path, info, times, core, selection, output, resume, max_seconds)


def validate_evidence(directory, plan, index, count, *, resume=False):
    """Audit arrays without Heyoka; resumption additionally validates exact MPFR state."""
    _, info, times, core, selection = problem(plan, index, count)
    report = json.loads((directory/"report.json").read_text())
    verify_report_identity(report, core, selection)
    verify_attempts(report)
    require(report["status"] in ("running", "completed", "checkpointed", "budget_exhausted", "integration_failed"),
            "Unknown partition state")
    require(set(report["traces"]) <= set(REQUESTS) and set(report["integrations"]) <= set(REQUESTS),
            "Unexpected integration inventory")
    traces = {label: load_trace(directory, report, label, info, times) for label in report["traces"]}
    if report["status"] == "completed":
        require(set(traces) == set(report["integrations"]) == set(REQUESTS)
                and all(report.get(k) == v for k, v in assess(traces).items()),
                "Completed control does not reproduce")
    verified = {}
    if resume:
        from .taylor_partition_resume import validate_checkpoint
        require(report["environment"] == partitions.environment(), "Resume environment differs")
        for label in ("taylor128", "taylor192"):
            path = directory/(label+"-checkpoint.npz")
            if path.exists():
                verified[label] = validate_checkpoint(path, info, times, selection, label)
            require(not report["integrations"].get(label, {}).get("interruption") or label in verified,
                    "Interrupted integration is missing its checkpoint")
    return {"report_sha256": digest(directory/"report.json"), "reported_status": report["status"],
            "completed_integrations": list(traces), "checkpoints": verified, "case_recovery_claimed": False}


def score_cases(plan, records):
    """Use the same three integrations in all twelve arms of every case."""
    results = {}
    for key, case in plan["cases"].items():
        ids = case["branches"]
        missing = {role: bid for role, bid in ids.items() if bid not in records}
        unconfirmed = {role: records[bid]["status"] for role, bid in ids.items()
                       if bid in records and records[bid]["status"] != "confirmed"}
        result = {"branches": ids, "missing_branches": missing, "unconfirmed_branches": unconfirmed,
                  "status": "incomplete" if missing else "failed"}
        if not missing and not unconfirmed:
            cells = {role: records[bid] for role, bid in ids.items()}
            scores = {label: {response: response_score(cells, label, response) for response in case["responses"]}
                      for label in REQUESTS}
            disagreements = [response for response in case["responses"] if any(
                classification_key(scores[label][response]) != classification_key(scores["taylor192"][response])
                for label in REQUESTS)]
            paper = {response: {label: [name for name, value in scores[label][response]["paper_like"].items()
                                       if value != scores["taylor192"][response]["paper_like"][name]]
                                for label in REQUESTS if label != "taylor192"} for response in case["responses"]}
            result.update(scores=scores, controlled_classification_disagreements=disagreements,
                          paper_like_disagreements=paper, status="mismatch" if disagreements else "passed")
        results[key] = result
    return results


def audit_cases(plan, directories, *, allow_partial=False):
    model = validate_plan(plan)
    records, summaries, runtime = {}, {}, None
    for directory in map(Path, directories):
        report = json.loads((directory/"report.json").read_text())
        selected = report["selection"]
        bid = selected["branch_id"]
        require(bid in plan["required_branch_ids"], "Unexpected branch; a short baseline is not a full sham")
        require(bid not in records, "Duplicate branch evidence")
        if bid in plan["control_branch_ids"]:
            args = problem(plan, selected["index"], selected["count"])
        else:
            index = plan["existing_failed_partition_indices"][bid]
            args = partitions.problem(model, index, plan["existing_failed_partition_count"])
        _, info, times, core, selection = args
        verify_report_identity(report, core, selection)
        verify_attempts(report)
        require(report["status"] == "completed"
                and set(report["traces"]) == set(report["integrations"]) == set(REQUESTS),
                "Three complete integrations are required for each supplied branch")
        if runtime is None:
            runtime = report["environment"]
        require(report["environment"] == runtime, "Cannot mix producer environments")
        traces = {label: load_trace(directory, report, label, info, times) for label in REQUESTS}
        outcome = assess(traces)
        require(all(report.get(k) == v for k, v in outcome.items()), "Saved comparisons do not reproduce")
        records[bid] = {"status": outcome["diagnostic_status"],
                        "windows": {label: summarize(trace, WINDOWS) for label, trace in traces.items()}}
        summaries[bid] = {"directory": str(directory), "report_sha256": digest(directory/"report.json"),
                          "trajectory_sha256": {label: report["traces"][label]["sha256"] for label in REQUESTS},
                          "samples": len(times), **outcome}
    missing = sorted(set(plan["required_branch_ids"])-records.keys())
    require(allow_partial or not missing, "All full-protocol branches and controls are required")
    cases = score_cases(plan, records)
    recovered = sum(case["status"] == "passed" for case in cases.values())
    return {"purpose": __doc__, "model_id": plan["model_id"], "case_plan_sha256": signature(plan),
            "environment": runtime, "engines_in_every_arm": list(REQUESTS), "expected_cases": len(cases),
            "recovered_cases": recovered, "complete_selected_case_coverage": not missing,
            "all_selected_cases_validated": recovered == len(cases), "missing_branch_ids": missing,
            "case_recovery_claimed": recovered > 0, "cases": cases, "branch_evidence": summaries,
            "audit_source_sha256": {name: digest(ROOT/name) for name in SOURCES}}
