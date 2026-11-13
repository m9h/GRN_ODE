"""Verify recorded Leloup refinement evidence; does not recompute trajectories."""

import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from diagnose_breaking_refinement import capture, digest, refinement_requests


def main():
    evidence = json.loads((HERE / "source-evidence.json").read_text())
    original = ROOT / "results/catalog-breaking-original-completed-20261112/BIOMD0000000021.json"
    assert evidence == capture(original), "Captured source failure inventory differs"
    report = json.loads((HERE / "report.json").read_text())
    assert report["status"] == "completed"
    assert report["model_id"] == "BIOMD0000000021"
    assert report["model_sha256"] == digest(ROOT / "models/BIOMD0000000021.xml")
    assert report["source_evidence_sha256"] == digest(HERE / "source-evidence.json")
    assert report["script_sha256"] == digest(ROOT / "scripts/diagnose_breaking_refinement.py")
    for name, value in report["implementation_sha256"].items():
        assert digest(ROOT / "grn_memory" / name) == value, name
    source = {b["record_id"]: b for b in evidence["failed_branches"]}
    assert len(source) == report["expected_branches"] == len(report["branches"]) == 12
    assert {b["record_id"] for b in report["branches"]} == set(source)
    required = ["roadrunner_tight_vs_copasi_tight", "roadrunner_tighter_vs_copasi_tighter",
                "roadrunner_tight_vs_roadrunner_tighter", "copasi_tight_vs_copasi_tighter"]
    maxima = {k: 0.0 for k in required}
    records = []
    for entry in report["branches"]:
        path = HERE / entry["file"]
        assert digest(path) == entry["sha256"]
        branch = json.loads(path.read_text())
        prior = source[entry["record_id"]]
        assert branch["source_record_id"] == entry["record_id"]
        assert branch["specification"] == prior["specification"]
        assert branch["original_comparison"] == prior.get("comparison")
        expected_keys = {e + "_" + r for e in ("roadrunner", "copasi")
                         for r in ("original", "tight", "tighter")}
        assert set(branch["integrations"]) == expected_keys
        for engine in ("roadrunner", "copasi"):
            for label, request in refinement_requests(prior["specification"]["integration_settings"][engine]).items():
                integration = branch["integrations"][engine + "_" + label]
                assert integration["request"] == request and integration["completed"]
                assert integration["samples"] == prior["sample_count"]
        for comparison in branch["comparisons"].values():
            assert comparison["samples"] == prior["sample_count"]
            assert comparison["passed"] == (comparison["max_scaled_error"] <= 1)
        for key in required:
            comparison = branch["comparisons"][key]
            assert comparison["passed"]
            maxima[key] = max(maxima[key], comparison["max_scaled_error"])
        assert branch["refinement_confirmed"] and entry["refinement_confirmed"]
        records.append({"record_id": entry["record_id"], "sha256": digest(path),
                        "samples": prior["sample_count"], "recorded_refinement_confirmed": True})
    assert report["confirmed_branches"] == 12
    result = {"scope": "Recorded-comparison and provenance verification; producer did not save raw diagnostic arrays.",
              "source_report_sha256": digest(original), "report_sha256": digest(HERE / "report.json"),
              "verification_script_sha256": digest(Path(__file__)),
              "complete_original_failed_branch_inventory": True, "branches": records,
              "completed_integrations": 72, "confirmed_branches": 12,
              "maximum_recorded_scaled_errors": maxima,
              "case_recovery_claimed": False, "full_model_validation_claimed": False}
    (HERE / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "branches"}))


if __name__ == "__main__":
    main()
