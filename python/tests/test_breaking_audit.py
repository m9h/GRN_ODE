"""Breaking evidence must retain complete observations, controls and search paths."""

from copy import deepcopy
import json
import shutil

import pytest

from grn_memory.breaking_audit import audit_branch, audit_case
from grn_memory.catalog_breaking import candidate_plans
from grn_memory.catalog_validation import ROOT, inspect_model
from scripts.audit_breaking_shards import read_archives


@pytest.fixture(scope="module")
def evidence():
    root=ROOT/"results/catalog-breaking-linux-27"
    reference=json.loads((ROOT/"results/catalog-repeated/BIOMD0000000275.json").read_text())
    plans=candidate_plans(reference)
    observables=inspect_model(ROOT/"models/BIOMD0000000275.xml")["observables"]
    partitions=[]
    for directory in sorted(root.glob("shard-*")):
        report=json.loads((directory/"BIOMD0000000275.json").read_text())
        partitions.append((directory,report,read_archives(directory,report,"branches"),read_archives(directory,report,"cases")))
    return reference,plans,observables,partitions


def example(evidence):
    reference,plans,observables,partitions=evidence
    for directory,report,branches,cases in partitions:
        for case in cases.values():
            if any(k.startswith("third__") for k in case["trials"]):
                return deepcopy(case),plans[case["case_key"]],branches,report,reference
    raise AssertionError("Published fixture must contain a conditional third trial")


def test_all_22_linux_cases_and_57_conditional_trials_reproduce(evidence):
    reference,plans,observables,partitions=evidence
    found=set()
    trials=0
    records=0
    for _,report,branches,cases in partitions:
        for branch in branches.values():
            assert audit_branch(branch,report,observables)
        records+=len(branches)
        for case in cases.values():
            key=case["case_key"]
            assert key not in found
            found.add(key)
            summary,used,unresolved=audit_case(case,plans[key],branches,report,reference)
            assert summary==report["cases"][key] and summary["status"]=="passed"
            assert used and not unresolved
            trials+=summary["evaluated_trials"]
    assert found==set(plans) and len(found)==22
    assert (trials,records)==(57,301)


def test_missing_conditional_third_trial_is_rejected(evidence):
    case,plan,branches,report,reference=example(evidence)
    del case["trials"][next(k for k in case["trials"] if k.startswith("third__"))]
    with pytest.raises(ValueError,match="required conditional trial"):
        audit_case(case,plan,branches,report,reference)


def test_omitted_control_cannot_be_replaced_by_stimulated_arms(evidence):
    case,plan,branches,report,reference=example(evidence)
    del case["trials"]["first"]["branches"]["none_sham"]
    with pytest.raises(ValueError,match="controls"):
        audit_case(case,plan,branches,report,reference)


def test_wrong_prior_probe_history_is_rejected(evidence):
    case,plan,branches,report,reference=example(evidence)
    roles=case["trials"]["second"]["branches"]
    roles["history_sham"]=case["trials"]["first"]["branches"]["history_sham"]
    with pytest.raises(ValueError,match="prior rechallenges"):
        audit_case(case,plan,branches,report,reference)


def test_saved_classification_must_match_recomputed_contrasts(evidence):
    case,plan,branches,report,reference=example(evidence)
    score=case["trials"]["first"]["scores"][report["engines"][0]]
    score[next(iter(score))]["category"]="fabricated"
    with pytest.raises(ValueError,match="scores do not reproduce"):
        audit_case(case,plan,branches,report,reference)


@pytest.mark.parametrize("corruption",["shortened_horizon","dropped_observable","failed_refinement"])
def test_full_branch_evidence_is_required(evidence,corruption):
    _,_,observables,partitions=evidence
    _,report,branches,_=partitions[0]
    branch=deepcopy(next(iter(branches.values())))
    if corruption=="shortened_horizon":
        branch["sample_count"]-=1
        branch["comparison"]["samples"]-=1
    elif corruption=="dropped_observable":
        del branch["comparison"]["per_observable_max_scaled_error"][observables[0]]
    else:
        branch["error"]="A later refinement failed after the first comparison passed"
    with pytest.raises(ValueError):
        audit_branch(branch,report,observables)


def test_archive_tampering_is_detected_before_scoring(evidence,tmp_path):
    _,_,_,partitions=evidence
    directory,report,_,_=partitions[0]
    shutil.copytree(directory,tmp_path,dirs_exist_ok=True)
    archive=tmp_path/report["evidence_archives"]["branches"][0]["file"]
    with archive.open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError,match="Archive digest"):
        read_archives(tmp_path,report,"branches")
