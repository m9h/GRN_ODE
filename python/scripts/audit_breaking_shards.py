"""Validate one complete model from disjoint breaking-case partitions.

Each case is audited against branch evidence from its own partition. Duplicate
branch identifiers across partitions are retained separately, never overwritten.
Recorded pointwise comparisons are checked; integration is not rerun here.
"""

import argparse
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from grn_memory.breaking_audit import audit_branch, audit_case, audit_comparison, require
from grn_memory.breaking_shards import outcome, select_cases
from grn_memory.catalog_breaking import candidate_plans, trial_windows
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_repeated import pulse_schedule
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import inspect_model


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(None)
def source_hash(revision,name):
    return hashlib.sha256(subprocess.check_output(["git","show",f"{revision}:python/{name}"],cwd=ROOT)).hexdigest()


def read_archives(directory,report,kind):
    records = {}
    for item in report["evidence_archives"][kind]:
        path = (directory/item["file"]).resolve()
        require(path.is_relative_to(directory.resolve()), "Archive path escapes the evidence directory")
        require(digest(path) == item["sha256"] and path.stat().st_size == item["bytes"], "Archive digest or size differs")
        count = 0
        with gzip.open(path,"rt") as stream:
            for line in stream:
                record = json.loads(line)
                require(record["record_id"] not in records, "Duplicate record within a partition")
                records[record["record_id"]] = record
                count += 1
        require(count == item["records"], "Archive record count differs")
    return records


def audit(directories, network):
    entries = json.loads((ROOT/"models/catalog.json").read_text())["models"]
    entry = next(e for e in entries if e["network"] == network)
    mid = entry["biomodel_id"]
    info = inspect_model(ROOT/"models"/(mid+".xml"))
    reference_path = ROOT/"results/catalog-repeated"/(mid+".json")
    reference = json.loads(reference_path.read_text())
    require(reference["status"] == "passed" and reference["model_sha256"] == info["sha256"], "Invalid repeated reference")
    plans = candidate_plans(reference)
    indices, fingerprints, all_cases, provenance = set(), set(), {}, []
    branch_records, branch_ids, controls, unresolved = 0, set(), [], []
    shard_count = None
    for directory in directories:
        manifest_path = directory/"shard.json"
        manifest = json.loads(manifest_path.read_text())
        require(manifest["network"] == network and manifest["model_id"] == mid, "Partition model differs")
        index,count = manifest["shard_index"],manifest["shard_count"]
        require(index not in indices and (shard_count is None or count == shard_count), "Duplicate index or different partition counts")
        shard_count = count
        indices.add(index)
        selection = {k: manifest[k] for k in ("network","model_id","shard_index","shard_count","candidate_plan_sha256",
            "reference_file_sha256","case_keys","expected_model_cases","selected_case_count")}
        expected = select_cases(plans,index,count)
        require(manifest["executed_control"] == (not plans and index == 0), "Untreated-control partition differs")
        require(manifest["selection_sha256"] == fingerprint(selection), "Partition selection digest differs")
        require(manifest["case_keys"] == expected and manifest["selected_case_count"] == len(expected), "Partition selection differs")
        require(manifest["expected_model_cases"] == len(plans) and manifest["candidate_plan_sha256"] == fingerprint(plans),
                "Partition candidate inventory differs")
        require(manifest["reference_file_sha256"] == digest(reference_path), "Partition calibration differs")
        revision = manifest["git_revision"]
        require(manifest["runner_sha256"] == source_hash(revision,"scripts/run_breaking_shard.py"), "Partition runner source differs")
        require(manifest["partition_source_sha256"] == source_hash(revision,"grn_memory/breaking_shards.py"), "Partition source differs")
        provenance.append({"directory": str(directory), "manifest_sha256": digest(manifest_path), "source_revision": revision})
        if not expected and not manifest["executed_control"]:
            require(manifest["status"] == "empty_shard" and not manifest["model_complete"], "Empty partition promoted model coverage")
            continue
        path = directory/(mid+".json")
        report = json.loads(path.read_text())
        require(digest(path) == manifest["model_report_sha256"], "Model report digest differs")
        meta = {k: report[k] for k in ("configuration","model_sha256","reference_fingerprint",
                "reference_file_sha256","implementation_sha256","versions")}
        require(fingerprint(meta) == report["fingerprint"] == manifest["model_fingerprint"], "Model fingerprint differs")
        fingerprints.add(report["fingerprint"])
        require(report["network"] == network and report["biomodel_id"] == mid, "Model report identity differs")
        require(report["model_sha256"] == info["sha256"], "Model source differs")
        require(report["reference_file_sha256"] == digest(reference_path) and report["reference_fingerprint"] == reference["fingerprint"],
                "Repeated-reference provenance differs")
        require(report["engines"] == reference["engines"], "Native engine inventory differs")
        for name,sha in report["implementation_sha256"].items():
            require(source_hash(revision,"grn_memory/"+name) == sha, f"Worker source differs: {name}")
        config = report["configuration"]
        require(config["dt"] == .01 and config["post_reset_offset"] == 1e-5, "Observation grid differs")
        require(config["comparison_rtol"] == 2e-5 and config["comparison_atol"] == 1e-7, "Comparison threshold differs")
        require(config["prefix"] == pulse_schedule() and config["trials"] == {k:list(v) for k,v in trial_windows(3).items()},
                "Protocol timeline differs")
        require(config["reset_interval"] == .1 and config["prefix_endpoint_resets"] and not config["later_endpoint_resets"]
                and config["later_resets_per_exposure"] == 999, "Reset timing differs")
        require(config["candidate_plan_sha256"] == fingerprint(plans), "Candidate plan differs")
        require(report["expected_cases"] == len(plans) and set(report["cases"]) == set(expected), "Partition case coverage differs")
        require(report["evaluated_cases"] == len(expected), "Evaluated case count differs")
        branches = read_archives(directory,report,"branches")
        cases = read_archives(directory,report,"cases")
        require(len(branches) == report["evaluated_unique_branches"], "Branch count differs")
        require(set(cases) == {fingerprint(plans[k]) for k in expected}, "Case evidence coverage differs")
        for branch in branches.values():
            audit_branch(branch,report,info["observables"])
        control_id = fingerprint({"reset_trains":[], "stop":2210., "integration_settings":config["integration_settings"]})
        require(control_id in branches, "Full untreated control is missing")
        control = branches[control_id]
        require(report["control_comparison"] == control.get("comparison",{"passed":False,"error":control.get("error")}),
                "Untreated comparison differs")
        controls.append(control["passed"])
        if config["timed_drive_encoding"]:
            require(set(report["encoding_control_comparisons"]) == set(report["engines"]), "Timed-drive controls missing")
            controls.extend(audit_comparison(c,221001,info["observables"]) for c in report["encoding_control_comparisons"].values())
        used = {control_id}
        for key in expected:
            require(key not in all_cases, "Overlapping initial cases between partitions")
            case = cases[fingerprint(plans[key])]
            require(case["case_key"] == key, "Case key differs")
            summary,ids,unknown = audit_case(case,plans[key],branches,report,reference)
            require(summary == report["cases"][key], "Case summary does not reproduce")
            used.update(ids)
            all_cases[key] = {**summary, "shard_index": index}
            unresolved.extend({"case":key,"trial":t} for t in unknown)
        require(used == set(branches), "Unreferenced or missing branch evidence")
        passed = sum(c["status"] == "passed" for c in report["cases"].values())
        require(report["passed_cases"] == passed, "Passed-case count differs")
        result = outcome(expected,report,execute_control=manifest["executed_control"],
                         returncode=manifest["returncode"],timed_out=manifest["timed_out"])
        require(all(manifest[k] == v for k,v in result.items()), "Partition outcome does not reproduce")
        require(result["selected_coverage_complete"], "Partition execution is incomplete")
        branch_records += len(branches)
        branch_ids.update(branches)
    require(indices == set(range(shard_count or 0)) and bool(indices), "Partition inventory is incomplete")
    require(len(fingerprints) == 1, "Cannot combine different model configurations or producer environments")
    require(set(all_cases) == set(plans), "Complete model case coverage is missing")
    passed = sum(c["status"] == "passed" for c in all_cases.values())
    validated = passed == len(plans) and all(controls) and bool(controls) and not unresolved
    return {"purpose":__doc__, **entry, "status":"passed" if validated else "incomplete_or_failed",
            "complete_case_coverage":True, "all_numerical_validations_passed":validated,
            "cases":len(plans), "passed_cases":passed, "partition_count":shard_count,
            "conditional_trials":sum(c["evaluated_trials"] for c in all_cases.values()),
            "response_trials":sum(c["evaluated_response_trials"] for c in all_cases.values()),
            "branch_records_across_partitions":branch_records, "distinct_branch_specifications":len(branch_ids),
            "unresolved_conditional_decisions":unresolved, "partitions":provenance,
            "case_summaries":all_cases, "audit_script_sha256":digest(Path(__file__)),
            "audit_module_sha256":digest(ROOT/"grn_memory/breaking_audit.py")}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network",type=int,required=True)
    parser.add_argument("--input",type=Path,action="append",required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=audit(args.input,args.network)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    write_json(args.output,result)
    print(json.dumps({k:result[k] for k in ("network","status","cases","passed_cases","conditional_trials","branch_records_across_partitions")}))
