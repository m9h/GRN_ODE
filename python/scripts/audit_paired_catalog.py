"""Audit complete paired-screen coverage without promoting failed trajectories.

This checks the archived evidence and recomputes scores from saved window
summaries. It does not rerun numerical integration or reconstruct trajectories.
"""

import argparse
from collections import Counter
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.catalog_paired import candidate_plans, case_branches, branch_id, branch_spec
from grn_memory.catalog_runner import fingerprint
from grn_memory.paired_scores import response_score, classification_key


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(None)
def source_digest(revision, name):
    content = subprocess.check_output(
        ["git", "show", f"{revision}:python/grn_memory/{name}"], cwd=ROOT)
    return hashlib.sha256(content).hexdigest()


def audit(directory, revision):
    catalog = json.loads((ROOT/"models/catalog.json").read_text())["models"]
    summary = json.loads((directory/"report.json").read_text())
    assert {m["network"] for m in summary["models"]} == {m["network"] for m in catalog}
    assert {p.stem for p in directory.glob("BIOMD*.json")} == {m["biomodel_id"] for m in catalog}
    totals, models, failures = Counter(), [], []
    for entry in catalog:
        mid = entry["biomodel_id"]
        path = directory/(mid+".json")
        model = json.loads(path.read_text())
        assert model["network"] == entry["network"] and model["biomodel_id"] == mid
        metadata = {k: model[k] for k in ("configuration", "model_sha256", "reference_fingerprint",
            "reference_file_sha256", "implementation_sha256", "versions")}
        assert fingerprint(metadata) == model["fingerprint"]
        config = model["configuration"]
        assert config["dt"] == .01 and config["post_reset_offset"] == 1e-5
        assert config["comparison_rtol"] == 2e-5 and config["comparison_atol"] == 1e-7
        reference_path = ROOT/"results/catalog-memory"/(mid+".json")
        reference = json.loads(reference_path.read_text())
        assert model["model_sha256"] == digest(ROOT/"models"/(mid+".xml"))
        assert model["reference_file_sha256"] == digest(reference_path)
        assert model["reference_fingerprint"] == reference["fingerprint"]
        for name, sha in model["implementation_sha256"].items():
            assert source_digest(revision, name) == sha, (mid, name)
        plans = candidate_plans(reference)
        assert fingerprint(plans) == model["configuration"]["candidate_plan_sha256"]
        assert model["cases"].keys() == plans.keys()
        assert model["expected_cases"] == model["evaluated_cases"] == len(plans)
        specs = {branch_id(s): s for p in plans.values() for s in case_branches(p).values()}
        specs[branch_id(branch_spec())] = branch_spec()
        archive = directory/model["branch_archive"]["file"]
        assert digest(archive) == model["branch_archive"]["sha256"]
        branches = {}
        with gzip.open(archive, "rt", encoding="utf-8") as stream:
            for line in stream:
                b = json.loads(line)
                key = b["branch_id"]
                assert key not in branches and specs[key] == b["specification"]
                assert b["fingerprint"] == model["fingerprint"]
                assert b["sample_count"] == 30001
                if "comparison" in b:
                    c = b["comparison"]
                    assert c["samples"] == 30001
                    assert c["passed"] == (c["max_scaled_error"] <= 1)
                if b["passed"]:
                    assert b["comparison"]["passed"] and "error" not in b
                    assert all(c["passed"] for c in b.get("refinement", {}).values())
                branches[key] = b
        assert branches.keys() == specs.keys()
        assert len(branches) == model["evaluated_unique_branches"]
        engines = model["engines"]
        for key, case in model["cases"].items():
            plan = plans[key]
            assert all(case[k] == plan[k] for k in ("ucs", "cs", "responses"))
            assert case["branches"] == {role: branch_id(s) for role, s in case_branches(plan).items()}
            cells = {role: branches[bid] for role, bid in case["branches"].items()}
            if all("windows" in b for b in cells.values()):
                scores = {e: {r: response_score(cells, e, r) for r in plan["responses"]} for e in engines}
                assert scores == case["scores"]
                disagree = [r for r in plan["responses"] if
                    classification_key(scores[engines[0]][r]) != classification_key(scores[engines[1]][r])]
                assert disagree == case["controlled_classification_disagreements"]
                passed = all(b["passed"] for b in cells.values()) and not disagree
                assert (case["status"] == "passed") == passed
            else:
                assert case["status"] == "failed"
            totals["response_assessments"] += len(plan["responses"])
            if case["status"] != "passed":
                failures.append({"network": entry["network"], "biomodel_id": mid,
                    "case": key, "status": case["status"],
                    "branch_failures": {role: {"branch_id": b["branch_id"],
                        **({"error": b["error"]} if "error" in b else {"comparison": b["comparison"]})}
                        for role, b in cells.items() if not b["passed"]},
                    "controlled_disagreements": case.get("controlled_classification_disagreements")})
        passed_cases = sum(c["status"] == "passed" for c in model["cases"].values())
        assert passed_cases == model["passed_cases"]
        passed_model = (passed_cases == len(plans) and all(b["passed"] for b in branches.values())
            and all(c["passed"] for c in model.get("encoding_control_comparisons", {}).values()))
        assert (model["status"] == "passed") == passed_model
        totals.update({"models": 1, "passed_models": int(model["status"] == "passed"),
            "cases": len(plans), "passed_cases": passed_cases, "branches": len(branches),
            "passed_branches": sum(b["passed"] for b in branches.values()),
            "incomplete_branches": sum("error" in b for b in branches.values()),
            "completed_mismatch_branches": sum(not b["passed"] and "error" not in b for b in branches.values())})
        models.append({"network": entry["network"], "biomodel_id": mid,
            "cases": len(plans), "passed_cases": passed_cases, "branches": len(branches),
            "report_sha256": digest(path), "branch_archive_sha256": digest(archive)})
    assert totals["models"] == summary["model_count"] == 35
    assert totals["passed_models"] == summary["passed_models"]
    assert totals["cases"] == summary["expected_cases"]
    assert totals["passed_cases"] == summary["passed_cases"]
    return {"purpose": __doc__, "source_revision": revision,
        "complete_catalog_coverage": True,
        "all_numerical_validations_passed": totals["passed_models"] == totals["models"],
        "aggregate_sha256": digest(directory/"report.json"), "totals": dict(totals),
        "models": models, "failed_cases": failures}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT/"results/catalog-paired")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args()
    result = audit(args.input, args.source_revision)
    output = args.output or args.input/"audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps(result["totals"]))
    print("Coverage/evidence audit passed; numerical validation:", result["all_numerical_validations_passed"])
