"""Plan and audit complete failed-case recoveries using SciPy diagnostics.

Original passing cases and newly recovered cases are reported separately. This
audits archived comparisons and recomputes scores, without rerunning integration
or recreating full trajectories from their window summaries.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.catalog_memory import write_json
from grn_memory.catalog_paired import WINDOWS, candidate_plans, case_branches, branch_id, branch_spec, reset_trains
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import inspect_model
from grn_memory.paired_recovery import (ENGINES, METADATA_KEYS, recover_cases, require,
                                      validate_comparison, validate_diagnostic_branch)
from grn_memory.paired_scores import response_score, classification_key


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def original_context(mid, directory, revision):
    path = directory/(mid+".json")
    model = json.loads(path.read_text())
    metadata = {k: model[k] for k in ("configuration", "model_sha256", "reference_fingerprint",
                "reference_file_sha256", "implementation_sha256", "versions")}
    require(fingerprint(metadata) == model["fingerprint"], "Original fingerprint differs")
    config = model["configuration"]
    require(config["dt"] == .01 and config["post_reset_offset"] == 1e-5, "Original grid differs")
    require(config["comparison_rtol"] == 2e-5 and config["comparison_atol"] == 1e-7, "Original acceptance differs")
    require(config["windows"] == {k: list(v) for k,v in WINDOWS.items()}, "Original windows differ")
    info = inspect_model(ROOT/"models"/(mid+".xml"))
    require(model["model_sha256"] == info["sha256"], "Original model hash differs")
    require(not config["timed_drive_encoding"], "Timed-drive recovery is not supported by this adapter")
    for name, sha in model["implementation_sha256"].items():
        content = subprocess.check_output(["git", "show", f"{revision}:python/grn_memory/{name}"], cwd=ROOT)
        require(hashlib.sha256(content).hexdigest() == sha, f"Original source differs: {name}")
    reference_path = ROOT/"results/catalog-memory"/(mid+".json")
    reference = json.loads(reference_path.read_text())
    require(digest(reference_path) == model["reference_file_sha256"], "Calibration file differs")
    require(reference["fingerprint"] == model["reference_fingerprint"], "Calibration fingerprint differs")
    plans = candidate_plans(reference)
    require(fingerprint(plans) == config["candidate_plan_sha256"], "Candidate plan differs")
    require(model["cases"].keys() == plans.keys(), "Original candidate coverage is incomplete")
    require(model["expected_cases"] == model["evaluated_cases"] == len(plans), "Original case counts differ")
    specs = {branch_id(s): s for p in plans.values() for s in case_branches(p).values()}
    specs[branch_id(branch_spec())] = branch_spec()
    archive = directory/model["branch_archive"]["file"]
    require(digest(archive) == model["branch_archive"]["sha256"], "Original branch archive differs")
    branches = {}
    with gzip.open(archive, "rt") as stream:
        for line in stream:
            b = json.loads(line)
            bid = b["branch_id"]
            require(bid not in branches and bid in specs, "Duplicate or unexpected original branch")
            require(b["specification"] == specs[bid] and b["fingerprint"] == model["fingerprint"],
                    "Original branch identity differs")
            require(b["reset_trains"] == [asdict(t) for t in reset_trains(specs[bid], reference)],
                    "Original reset schedule differs")
            require(b["sample_count"] == 30001, "Original branch has incomplete observation grid")
            if "comparison" in b:
                validate_comparison(b["comparison"], info["observables"])
            if b["passed"]:
                require(b["comparison"]["passed"] and "error" not in b, "Original branch pass is inconsistent")
                require(all(c["passed"] for c in b.get("refinement", {}).values()), "Original refinement failed")
            branches[bid] = b
    require(branches.keys() == specs.keys(), "Original branch coverage is incomplete")
    require(len(branches) == model["expected_unique_branches"] == model["evaluated_unique_branches"],
            "Original branch counts differ")
    engines = model["engines"]
    for key, plan in plans.items():
        case = model["cases"][key]
        require(all(case[k] == plan[k] for k in ("ucs", "cs", "responses")), "Original case plan differs")
        ids = {role: branch_id(s) for role,s in case_branches(plan).items()}
        require(case["branches"] == ids, "Original case arm inventory differs")
        cells = {role: branches[bid] for role,bid in ids.items()}
        if all("windows" in b for b in cells.values()):
            scores = {e: {r: response_score(cells,e,r) for r in plan["responses"]} for e in engines}
            require(case["scores"] == scores, "Original scores do not reproduce")
            disagree = [r for r in plan["responses"] if
                        classification_key(scores[engines[0]][r]) != classification_key(scores[engines[1]][r])]
            require(disagree == case["controlled_classification_disagreements"], "Original classifications differ")
            passed = all(b["passed"] for b in cells.values()) and not disagree
            require((case["status"] == "passed") == passed, "Original case status contradicts evidence")
        else:
            require(case["status"] == "failed", "Original incomplete case was promoted")
    require(sum(c["status"] == "passed" for c in model["cases"].values()) == model["passed_cases"],
            "Original passed-case count differs")
    return model, plans, branches, info, path


def audit(args):
    mid = f"BIOMD{args.model:010d}"
    original, plans, branches, info, source = original_context(mid, args.input, args.source_revision)
    required = {bid for c in original["cases"].values() if c["status"] != "passed"
                for bid in c["branches"].values()}
    provenance, records, record_sources, selected, signatures = [], {}, {}, set(), set()
    for directory in args.diagnostics:
        path = directory/"report.json"
        report_bytes = path.read_bytes()
        report = json.loads(report_bytes)
        metadata = {k: report[k] for k in METADATA_KEYS}
        require(fingerprint(metadata) == report["fingerprint"], "Diagnostic metadata fingerprint differs")
        signatures.add(report["fingerprint"])
        require(report["model_id"] == mid and report["model_sha256"] == info["sha256"], "Diagnostic model differs")
        require(report["source_report_sha256"] == digest(source), "Diagnostic original report differs")
        require(report["source_fingerprint"] == original["fingerprint"], "Diagnostic original fingerprint differs")
        require(report["source_archive_sha256"] == original["branch_archive"]["sha256"], "Diagnostic archive differs")
        require(report["grid"] == {"duration": 300., "dt": .01, "post_reset_offset": 1e-5, "samples": 30001},
                "Diagnostic grid differs")
        require(report["comparison_settings"] == {"rtol": 2e-5, "atol": 1e-7}, "Diagnostic acceptance differs")
        require(report["script_sha256"] == digest(ROOT/"scripts/diagnose_scipy_paired.py"), "Diagnostic script differs")
        requests = report["integration_requests"]
        require(set(requests) == {"scipy", "scipy_refined", "roadrunner", "roadrunner_refined", "roadrunner_original"},
                "Diagnostic integration inventory differs")
        require(requests["roadrunner_original"] == original["configuration"]["integration_settings"]["roadrunner"],
                "Diagnostic original integration request differs")
        for engine in ("scipy", "roadrunner"):
            for key in ("rtol", "atol"):
                base, refined = requests[engine][key], requests[engine+"_refined"][key]
                require(math.isfinite(base) and 0 < refined < base, "Diagnostic request is not a refinement")
        # Source hashes are checked against installed/local files. This audit is
        # deliberately strict: use the recorded checkout and environment.
        from grn_memory.catalog_jax import source_hashes
        sources = source_hashes()
        sources.update({"grn_memory/"+n: digest(ROOT/"grn_memory"/n) for n in
                        ("scipy_reference.py", "jax_protocols.py", "catalog_repeated.py", "catalog_paired.py")})
        require(report["implementation_sha256"] == sources, "Diagnostic implementation hashes differ")
        require(all(version(p) == v for p,v in report["versions"].items()), "Diagnostic environment differs")
        ids = report["selected_branch_ids"]
        require(len(ids) == len(set(ids)) == report["expected_branches"], "Diagnostic selection count differs")
        require(set(ids) <= branches.keys(), "Diagnostic contains unknown branches")
        selected.update(ids)
        provenance.append({"directory": str(directory), "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
                           "fingerprint": report["fingerprint"], "status_at_audit": report["status"]})
        for bid in ids:
            if bid not in required:
                continue
            record_path = directory/(bid+".json")
            if not record_path.exists():
                continue
            record = json.loads(record_path.read_text())
            if record["status"] == "running":
                continue
            validate_diagnostic_branch(record, report, branches[bid], info["observables"])
            require(bid not in records, "Duplicate diagnostic evidence: choose one declared run per branch")
            records[bid] = record
            record_sources[bid] = {"file": str(record_path), "sha256": digest(record_path)}
    require(len(signatures) <= 1, "Cannot mix diagnostic configurations, source versions or environments")
    cases = recover_cases(plans, original["cases"], records)
    recovered = sum(c["status"] == "passed" for c in cases.values())
    combined = original["passed_cases"]+recovered
    return {"purpose": __doc__, "model_id": mid, "model_sha256": info["sha256"],
            "source_revision": args.source_revision, "source_report_sha256": digest(source),
            "source_archive_sha256": original["branch_archive"]["sha256"],
            "audit_script_sha256": digest(Path(__file__)),
            "scoring_source_sha256": {n: digest(ROOT/"grn_memory"/n) for n in ("paired_recovery.py", "paired_scores.py")},
            "audited_at": datetime.now(timezone.utc).isoformat(), "original_case_count": len(plans),
            "original_passed_cases": original["passed_cases"], "recovery_engines": ENGINES,
            "expected_recovery_cases": len(cases), "recovered_cases": recovered,
            "combined_passed_cases": combined, "all_cases_validated": combined == len(plans),
            "status": "passed" if combined == len(plans) else "incomplete_or_failed",
            "required_branch_ids": sorted(required), "required_branch_count": len(required),
            "unselected_branch_ids": sorted(required-selected),
            "missing_terminal_branch_ids": sorted(required-records.keys()),
            "confirmed_branches": sum(r["status"] == "confirmed" for r in records.values()),
            "diagnostics": provenance, "branch_evidence": record_sources, "cases": cases}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=int, required=True)
    parser.add_argument("--input", type=Path, default=ROOT/"results/catalog-paired")
    parser.add_argument("--diagnostics", type=Path, action="append", default=[])
    parser.add_argument("--source-revision", default="70a3afad61357e94873ff62a7300c099b4c7ae3e")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result)
    print(json.dumps({k: result[k] for k in ("model_id", "status", "required_branch_count",
        "confirmed_branches", "original_passed_cases", "recovered_cases", "combined_passed_cases")}))
