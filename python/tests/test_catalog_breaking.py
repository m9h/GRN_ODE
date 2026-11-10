"""Distinguish restoration of a history effect from direct or residual forcing."""

from copy import deepcopy
import gzip
import hashlib
import json

import pytest

from grn_memory.breaking_scores import controlled_break, matlab_break_direction, remaining_responses
from grn_memory.catalog_archive import EvidenceStore
from grn_memory.catalog_breaking import branch_trains, candidate_plans, next_breakers, trial_windows
from grn_memory.catalog_runner import ROOT, fingerprint


def test_residual_levels_do_not_create_a_rechallenge_history_effect():
    # Different histories have different residual levels but identical cue gains.
    cells = {"none":(3.,1.), "history":(6.,4.), "breaker":(8.,6.), "history_breaker":(10.,8.)}
    assert controlled_break(cells)["category"] == "no_resolved_history_effect_at_rechallenge"


def test_a_direct_breaker_effect_shared_by_naive_and_trained_systems_is_removed():
    # Trained cue gain is 1 instead of 3. The breaker adds 4 to both cue gains.
    cells = {"none":(4.,1.), "history":(2.,1.), "breaker":(8.,1.), "history_breaker":(6.,1.)}
    score = controlled_break(cells)
    assert score["history_effect_without_breaker"]["value"] == -2.
    assert score["history_effect_with_breaker"]["value"] == -2.
    assert score["category"] == "no_resolved_breaker_effect_on_history"


def test_restoration_and_overshoot_are_distinct_from_threshold_and_negative_states():
    cells = {"none":(4.,1.), "history":(2.,1.), "breaker":(4.,1.), "history_breaker":(4.,1.)}
    assert controlled_break(cells)["category"] == "history_effect_reduced_by_half"
    assert controlled_break(cells,negative=True)["category"] == "negative_response_state"
    cells["history_breaker"] = (3.,1.)
    assert controlled_break(cells)["category"] == "half_restoration_threshold_unresolved"
    cells["history_breaker"] = (7.,1.)
    assert controlled_break(cells)["category"] == "history_effect_reversed"


def test_raw_reversal_and_continuation_keep_zero_artifacts_and_engine_union_explicit():
    assert matlab_break_direction(1.,2.,2) == 1
    assert matlab_break_direction(3.,1.,1) == 2
    assert matlab_break_direction(1.,1.,1) == 0
    assert matlab_break_direction(0.,0.,2) == 1  # Original raw equality artifact.
    scores = {e:{r:{"matlab":{"eligible":True,"break_direction":1}} for r in ("R1","R2")}
              for e in ("a","b")}
    scores["b"]["R1"]["matlab"] = {"eligible":False,"break_direction":0}
    scores["b"]["R2"]["matlab"]["break_direction"] = 0
    assert remaining_responses(scores,["R1","R2"],["a","b"]) == ["R2"]


def _reference():
    return {"cases":{s+"__up":{"input":s,"level":100.} for s in "UBCR"}}


def test_third_trial_preserves_every_earlier_rechallenge_and_native_time():
    reference = _reference()
    trains = branch_trains("U__up",["B__up","B__up","C__up"],True,True,True,reference)
    assert [(t.start,t.stop) for t in trains[-6:]] == [
        (1010.,1110.),(1210.,1310.),(1410.,1510.),(1610.,1710.),(1810.,1910.),(2010.,2110.)]
    assert sum(len(t.times()) for t in trains) == 10500
    assert trains[6].times()[0] == pytest.approx(1010.1)
    assert trains[-1].times()[-1] == pytest.approx(2109.9)
    sham = branch_trains("U__up",["B__up","B__up","C__up"],True,True,False,reference)
    assert [(t.start,t.stop) for t in sham] == [(t.start,t.stop) for t in trains[:-1]]
    assert trial_windows(3)["post_3"] == (2110.,2210.)


def test_new_breaker_has_four_distinct_roles_and_zero_levels_are_not_invented():
    reference = _reference()
    plan = {"ucs":"U__up","breaker":"B__up"}
    assert next_breakers(plan,["R"],reference) == {"C__up":["R"]}
    reference["cases"]["C__up"]["level"] = 0
    assert next_breakers(plan,["R"],reference) == {}


def test_evidence_resume_shards_and_provenance_are_complete(tmp_path):
    signature = fingerprint({"configuration":1})
    store = EvidenceStore(tmp_path,"model",signature)
    keys = [fingerprint({"branch":i}) for i in range(3)]
    for i,key in enumerate(keys):
        store.put("branches",key,{"passed":i != 2,"value":i})
    assert len(store.recent) <= 8
    assert EvidenceStore(tmp_path,"model",signature).get("branches",keys[0]) is None
    resumed = EvidenceStore(tmp_path,"model",signature,True)
    assert resumed.get("branches",keys[0])["value"] == 0
    assert resumed.get("branches",keys[2]) is None
    assert resumed.get("branches",keys[2],passed_only=False)["value"] == 2
    assert EvidenceStore(tmp_path,"model",fingerprint({"configuration":2}),True).get("branches",keys[0]) is None
    manifest = resumed.publish(shard_records=1)
    assert sum(p["records"] for p in manifest["branches"]) == 2
    records=[]
    for item in manifest["branches"]:
        path=tmp_path/item["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        with gzip.open(path,"rt") as f:
            records.extend(json.loads(line) for line in f)
    assert {r["record_id"] for r in records} == {keys[0],keys[2]}


def test_exhaustive_initial_breaking_inventory_covers_both_raw_cohorts():
    pairs=assessments=0
    no_candidates=[]
    catalog=json.loads((ROOT/"models/catalog.json").read_text())["models"]
    for entry in catalog:
        reference=json.loads((ROOT/"results/catalog-repeated"/f'{entry["biomodel_id"]}.json').read_text())
        plans=candidate_plans(reference)
        pairs+=len(plans)
        if not plans:
            no_candidates.append(entry["network"])
        for plan in plans.values():
            u,b=(reference["cases"][plan[k]]["input"] for k in ("ucs","breaker"))
            for response, source in plan["responses"].items():
                assessments+=1
                assert len({u,b,response}) == 3
                assert any(s["eligible"] for s in source.values())
    assert (pairs,assessments)==(7324,37086)
    assert no_candidates==[6,14,17,33]
