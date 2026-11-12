"""Compare recorded search paths and labels after auditing two complete runs.

This compares a complete local report with complete disjoint partitions. It
does not rerun trajectories or infer agreement on trials unique to either run.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import require
from grn_memory.breaking_scores import classification_key
from grn_memory.catalog_memory import write_json
from scripts.audit_breaking_catalog import audit_model
from scripts.audit_breaking_shards import audit as audit_shards, digest, read_archives


def compare_cases(left, right, engines):
    require(left.keys() == right.keys(), "Complete matching case inventories are required")
    totals = Counter(cases=len(left), shared_trials=0, shared_response_engine_assessments=0,
                     left_only_trials=0, right_only_trials=0, shared_response_inventory_differences=0)
    paths, raw, controlled = [], [], []
    for key in sorted(left):
        a, b = left[key]["trials"], right[key]["trials"]
        describe = lambda trials: {name: {k: row[k] for k in ("breakers", "responses")}
                                    for name, row in sorted(trials.items())}
        if describe(a) != describe(b):
            paths.append({"case": key, "left": describe(a), "right": describe(b)})
        totals["left_only_trials"] += len(a.keys()-b.keys())
        totals["right_only_trials"] += len(b.keys()-a.keys())
        for name in sorted(a.keys() & b.keys()):
            first, second = a[name], b[name]
            require(first["breakers"] == second["breakers"], "A shared trial has different interventions")
            totals["shared_trials"] += 1
            totals["shared_response_inventory_differences"] += first["responses"] != second["responses"]
            require(set(first.get("scores", {})) == set(second.get("scores", {})) == set(engines),
                    "Shared trials require complete engine score inventories")
            for engine in engines:
                one, two = first["scores"][engine], second["scores"][engine]
                require(set(one) == set(first["responses"]) and set(two) == set(second["responses"]),
                        "Shared trials require every declared response score")
                for response in sorted(one.keys() & two.keys()):
                    x, y = one[response], two[response]
                    totals["shared_response_engine_assessments"] += 1
                    identity = {"case": key, "trial": name, "engine": engine, "response": response}
                    if x["matlab"]["break_direction"] != y["matlab"]["break_direction"]:
                        fields = ("pre_mean", "cue_mean", "last_code", "break_direction")
                        values = [abs(s["matlab"][k]) for s in (x, y) for k in ("pre_mean", "cue_mean")]
                        raw.append({**identity, "left": {k: x["matlab"][k] for k in fields},
                                    "right": {k: y["matlab"][k] for k in fields},
                                    "largest_mean_magnitude": max(values),
                                    "all_means_below_absolute_comparison_floor": max(values) < 1e-7})
                    if classification_key(x) != classification_key(y):
                        controlled.append({**identity, "left": classification_key(x), "right": classification_key(y)})
    totals.update(path_differing_cases=len(paths), raw_reversal_label_differences=len(raw),
                  controlled_label_differences=len(controlled),
                  raw_differences_below_absolute_floor=sum(r["all_means_below_absolute_comparison_floor"] for r in raw))
    return {"totals": dict(totals), "largest_mean_in_raw_disagreements":
            max((r["largest_mean_magnitude"] for r in raw), default=None),
            "path_differences": paths, "raw_label_differences": raw,
            "controlled_label_differences": controlled,
            "controlled_agreement_on_shared_assessments":
            (not controlled if totals["shared_response_engine_assessments"] else None),
            "whole_run_equivalence_claimed": False, "trajectory_reintegration_performed": False}


def compare(directory, partitions, network, revision):
    entries = json.loads((ROOT/"models/catalog.json").read_text())["models"]
    entry = next(e for e in entries if e["network"] == network)
    left_audit = audit_model(directory, entry, revision)
    right_audit = audit_shards(partitions, network)
    filename = entry["biomodel_id"]+".json"
    local_path = directory/filename
    local = json.loads(local_path.read_text())
    left_rows = read_archives(directory, local, "cases")
    left = {k: left_rows[v["record_id"]] for k, v in local["cases"].items()}
    right, provenance = {}, []
    for partition in partitions:
        path = partition/filename
        if not path.exists():
            continue  # Empty partitions were checked by the complete-model audit.
        report = json.loads(path.read_text())
        for key in ("model_sha256", "reference_file_sha256", "reference_fingerprint", "configuration", "versions", "engines"):
            require(report[key] == local[key], "Run context differs: "+key)
        rows = read_archives(partition, report, "cases")
        require(not (right.keys() & report["cases"].keys()), "Duplicate partition cases")
        right.update({k: rows[v["record_id"]] for k, v in report["cases"].items()})
        provenance.append({"directory": str(partition), "report_sha256": digest(path)})
    result = compare_cases(left, right, local["engines"])
    return {"purpose": __doc__, "network": network, "model_id": entry["biomodel_id"],
            "local_source_revision": revision, "local_report_sha256": digest(local_path),
            "partition_reports": provenance, "local_audit": left_audit, "partition_audit": right_audit,
            **result, "comparison_script_sha256": digest(Path(__file__))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--partition", type=Path, action="append", required=True)
    parser.add_argument("--network", type=int, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.local, args.partition, args.network, args.source_revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result)
    print(json.dumps(result["totals"]))
