"""Reconstruct complete candidate controls for independently checked breaking cases.

The original source selection and calibration remain fixed. All possible third
trials are computed, but an eventual case audit must replay the conditional
search from the new trajectories; this inventory cannot claim case recovery.
"""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import gzip
import json
from pathlib import Path
import subprocess

from .breaking_audit import audit_branch, audit_case, require
from .catalog_breaking import branch_trains, candidate_plans, next_breakers, trial_windows
from .catalog_repeated import pulse_schedule, trains_for
from .catalog_runner import ROOT, fingerprint
from .jax_protocols import supported_model
from .native_protocols import ResetTrain, sample_times


LABELS = ("roadrunner", "roadrunner_refined", "scipy", "scipy_refined")
ACCEPTANCE = {"rtol": 2e-5, "atol": 1e-7}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def common_eligibility(plan):
    """Transfer only source eligibility on which both original engines agree."""
    result = {}
    for response, values in plan["responses"].items():
        require(set(values) == {"roadrunner", "copasi"}
                and values["roadrunner"] == values["copasi"],
                "Original engine eligibility differs; no unambiguous transfer is supported")
        result[response] = {label: deepcopy(values["roadrunner"]) for label in LABELS}
    return result


def potential_trials(plan, reference):
    breaker = plan["breaker"]
    return {"first": [breaker], "second": [breaker, breaker],
            **{"third__" + third: [breaker, breaker, third]
               for third in next_breakers(plan, list(plan["responses"]), reference)}}


def trial_specifications(plan, breakers, reference, config):
    settings = {**config["integration_settings"],
                **config["case_integration_overrides"].get(plan["ucs"], {})}
    result = {}
    for name, history, breaking in (("none", False, False), ("history", True, False),
                                    ("breaker", False, True), ("history_breaker", True, True)):
        for cue in (False, True):
            result[name + ("_cue" if cue else "_sham")] = {
                "reset_trains": [asdict(t) for t in branch_trains(
                    plan["ucs"], breakers, history, breaking, cue, reference)],
                "stop": 1010. + 400 * len(breakers), "integration_settings": deepcopy(settings)}
    return result


def prepare_inventory(evidence_path, case_plan_path, source_revision, branch_archive_path=None):
    evidence = json.loads(Path(evidence_path).read_text())
    captured = json.loads(Path(case_plan_path).read_text())
    original = evidence["original_report"]
    config = original["configuration"]
    mid = original["biomodel_id"]
    path = ROOT / "models" / (mid + ".xml")
    info = supported_model(path)
    metadata = {k: original[k] for k in ("configuration", "model_sha256", "reference_fingerprint",
                "reference_file_sha256", "implementation_sha256", "versions")}
    require(fingerprint(metadata) == original["fingerprint"], "Original fingerprint differs")
    require(info["sha256"] == original["model_sha256"] and original["engines"] == ["roadrunner", "copasi"],
            "Original model or engines differ")
    require(captured["model_id"] == mid and captured["source_report_sha256"] == evidence["original_report_sha256"],
            "Original case-plan source differs")
    require(config["dt"] == .01 and config["post_reset_offset"] == 1e-5
            and {k: config["comparison_" + k] for k in ACCEPTANCE} == ACCEPTANCE
            and not config["timed_drive_encoding"], "Original grid, acceptance or encoding differs")
    require(config["prefix"] == pulse_schedule()
            and config["trials"] == {k: list(v) for k, v in trial_windows(3).items()}
            and config["reset_interval"] == .1 and config["prefix_endpoint_resets"] is True
            and config["later_endpoint_resets"] is False and config["later_resets_per_exposure"] == 999,
            "Original intervention timeline differs")
    for name, expected in original["implementation_sha256"].items():
        source = subprocess.check_output(["git", "show", f"{source_revision}:python/grn_memory/{name}"], cwd=ROOT)
        require(hashlib.sha256(source).hexdigest() == expected, "Original producer source differs: " + name)
    reference_path = ROOT / "results/catalog-repeated" / (mid + ".json")
    reference = json.loads(reference_path.read_text())
    require(digest(reference_path) == original["reference_file_sha256"]
            and reference["fingerprint"] == original["reference_fingerprint"]
            and reference["model_sha256"] == info["sha256"] and reference["status"] == "passed",
            "Original validated calibration differs")
    plans = candidate_plans(reference)
    require(fingerprint(plans) == config["candidate_plan_sha256"]
            and len(plans) == original["expected_cases"], "Original candidate inventory differs")
    selected = sorted(k for k, c in original["cases"].items() if c["status"] != "passed")
    require(bool(selected) and set(captured["cases"]) == set(selected), "Complete original failed-case inventory is required")
    captured_specs = captured["selected_branches"]
    require(isinstance(captured_specs, dict) and captured["required_branch_count"] == len(captured_specs),
            "Captured branch count differs")
    branch_archive_path = Path(branch_archive_path or Path(case_plan_path).parent / "source-branches.jsonl.gz")
    provenance_path = branch_archive_path.parent / "source-branches-provenance.json"
    provenance = json.loads(provenance_path.read_text())
    require(provenance["source_report_sha256"] == evidence["original_report_sha256"]
            and provenance["source_fingerprint"] == original["fingerprint"]
            and provenance["selected_archive_sha256"] == digest(branch_archive_path)
            and provenance["selected_archive_bytes"] == branch_archive_path.stat().st_size,
            "Original selected-branch archive provenance differs")
    expected_archives = {e["file"]: e["sha256"] for kind in ("branches", "cases")
                         for e in original["evidence_archives"][kind]}
    require(provenance["verified_original_archives"] == expected_archives,
            "Original archive inventory differs")
    branches = {}
    with gzip.open(branch_archive_path, "rt") as stream:
        for line in stream:
            branch = json.loads(line)
            bid = branch["record_id"]
            require(bid not in branches, "Duplicate original branch record")
            branches[bid] = branch
    require(set(branches) == set(captured_specs)
            and provenance["selected_branch_ids"] == sorted(branches)
            and provenance["selected_branch_count"] == len(branches),
            "Selected original branch inventory differs")
    for bid, branch in branches.items():
        require(branch["record_id"] == bid, "Captured branch identity differs")
        require(captured_specs[bid] == {"specification": branch["specification"],
                "sample_count": branch["sample_count"], "original_passed": branch["passed"]},
                "Captured branch specification differs")
        audit_branch(branch, original, info["observables"])
    source_failed = {b["record_id"]: b for b in evidence["failed_branches"]}
    require({bid for bid, b in branches.items() if not b["passed"]} == set(source_failed)
            and all(branches[bid] == b for bid, b in source_failed.items()),
            "Captured original failed branches differ")
    specs, cases, used = {}, {}, set()
    for key in selected:
        plan = plans[key]
        eligible = common_eligibility(plan)
        prior = captured["cases"][key]
        summary, ids, unknown = audit_case(prior["case"], plan, branches, original, reference)
        require(summary == prior["summary"] == original["cases"][key]
                and unknown == prior["unresolved_conditional_decisions"], "Original case evidence differs")
        used.update(ids)
        trials = {}
        for name, breakers in potential_trials(plan, reference).items():
            roles = {}
            for role, spec in trial_specifications(plan, breakers, reference, config).items():
                bid = fingerprint(spec)
                specs[bid] = spec
                roles[role] = bid
            trials[name] = {"breakers": breakers, "branches": roles}
        cases[key] = {"original_plan": plan, "shared_source_eligibility": eligible, "potential_trials": trials}
    require(used == set(branches) == set(specs),
            "Captured controls do not cover every possible conditional continuation")
    require(all(branches[bid]["specification"] == spec for bid, spec in specs.items()),
            "Reconstructed original branch specification differs")
    baseline = {"reset_trains": [], "stop": 2210., "integration_settings": deepcopy(config["integration_settings"])}
    baseline_id = fingerprint(baseline)
    specs[baseline_id] = baseline
    possible = trains_for(pulse_schedule(), {}) + [ResetTrain(t, t + 100., {})
                for t in (1010., 1210., 1410., 1610., 1810., 2010.)]
    grid = sample_times(2210., .01, possible, post_reset_offset=1e-5)
    inventory = {"model_id": mid, "model_sha256": info["sha256"], "source_revision": source_revision,
                 "source_report_sha256": evidence["original_report_sha256"],
                 "source_evidence_sha256": digest(evidence_path), "case_plan_sha256": digest(case_plan_path),
                 "original_branch_archive_sha256": digest(branch_archive_path),
                 "original_branch_provenance_sha256": digest(provenance_path),
                 "calibration_sha256": digest(reference_path), "cases": cases, "branches": specs,
                 "full_untreated_control": baseline_id, "expected_branches": len(specs),
                 "expected_model_cases": len(plans),
                 "original_case_branches": len(branches), "case_recovery_claimed": False,
                 "conditional_search_must_be_recomputed": True}
    return inventory, path, info, grid
