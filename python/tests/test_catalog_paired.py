"""Controls that keep persistent or age-dependent responses out of learning claims."""

from copy import deepcopy
import json

import pytest

from grn_memory.catalog_paired import candidate_plans, case_branches, branch_id, reset_trains
from grn_memory.catalog_validation import ROOT
from grn_memory.paired_scores import controlled_probe, contrast, paper_labels, response_score


def test_residual_stimulation_and_clock_dependent_cue_response_are_controlled():
    residual = {"none": (1.,1.), "ucs": (4.,4.), "cs": (1.,1.), "paired": (6.,6.)}
    assert controlled_probe(residual)["category"] == "unresolved_cue_effect"
    # Each history has the same +3 effect of the later cue, despite different
    # remaining trained levels. An early negative CS pretest cannot detect this.
    clock = {h:(on+3,sham) for h,(on,sham) in residual.items()}
    score = controlled_probe(clock)
    assert score["category"] == "cue_response_without_joint_specificity"
    assert score["factorial_interaction"]["value"] == 0


@pytest.mark.parametrize("single", ["ucs", "cs"])
def test_either_input_alone_explains_the_response_without_joint_specificity(single):
    cells = {h:(1.,1.) for h in ("none", "ucs", "cs", "paired")}
    cells[single] = cells["paired"] = (4.,1.)
    score = controlled_probe(cells)
    assert score["category"] == "cue_response_without_joint_specificity"
    assert score["factorial_interaction"]["resolved_direction"] == 0
    assert score[single+"_history_effect"]["resolved_direction"] == 1


def test_additive_history_effects_are_not_nonadditive_pairing():
    # Cue effects are 0, 2, 3 and 5. Both histories contribute independently.
    score = controlled_probe({"none": (1.,1.), "ucs": (3.,1.), "cs": (4.,1.), "paired": (6.,1.)})
    assert score["category"] == "cue_response_without_joint_specificity"
    assert score["factorial_interaction"]["value"] == 0


def test_joint_exposure_candidate_requires_resolved_nonadditivity_and_valid_states():
    cells = {"none": (1.,1.), "ucs": (1.,1.), "cs": (1.,1.), "paired": (5.,1.)}
    assert controlled_probe(cells)["category"] == "joint_exposure_candidate"
    assert controlled_probe(cells, negative=True)["category"] == "negative_response_state"
    tiny = deepcopy(cells)
    tiny["paired"] = (1.+1e-8,1.)
    assert controlled_probe(tiny)["category"] == "unresolved_cue_effect"
    assert contrast([(1., 1.), (-1., 1.+1e-8)])["resolved_direction"] == 0


def test_boolean_recall_and_postprobe_relaxation_are_distinct_from_delayed_cue():
    m = {"baseline": 1., "control_train": 1., "control_probe": 1., "control_postprobe": 1.,
         "ucs_train": 3., "ucs_wash": 1., "cs_train": 1., "paired_train": 3., "paired_wash": 1.,
         "ucs_probe": 1., "paired_probe": 3., "paired_postprobe": 1.,
         "delayed_preprobe": 1., "delayed_probe": 1., "delayed_sham": 1.}
    labels = paper_labels(m)
    assert labels["association"] and labels["short_recall"] and not labels["long_recall"]
    assert not labels["ucs_memory"] and not labels["pairing_memory"]
    m.update(paired_probe=1., paired_postprobe=3., delayed_probe=1.)
    labels = paper_labels(m)
    assert labels["matlab_later_relaxation_candidate"] and not labels["delayed_cue_candidate"]
    m.update(paired_postprobe=1., delayed_probe=3.)
    labels = paper_labels(m)
    assert labels["delayed_cue_candidate"] and not labels["matlab_later_relaxation_candidate"]


def test_control_schedules_are_shared_only_when_histories_are_identical():
    plan = {"ucs": "U__up", "cs": "C__down"}
    branches = case_branches(plan)
    reverse = case_branches({"ucs": "C__down", "cs": "U__up"})
    assert len(set(map(branch_id, branches.values()))) == 12
    assert branch_id(branches["paired_sham"]) == branch_id(reverse["paired_sham"])
    assert branch_id(branches["paired_normal"]) != branch_id(reverse["paired_normal"])
    reference = {"cases": {"U__up": {"input": "U", "level": 100.}, "C__down": {"input": "C", "level": .01}}}
    trains = reset_trains(branches["paired_delayed"], reference)
    assert [len(t.times()) for t in trains] == [499,499]
    assert trains[0].times()[0] == pytest.approx(50.1)
    assert trains[0].times()[-1] == pytest.approx(99.9)
    assert trains[1].times()[0] == pytest.approx(200.1)
    assert trains[1].times()[-1] == pytest.approx(249.9)
    assert trains[0].values == {"U":100., "C":.01}
    assert trains[1].values == {"C":.01}


def test_ordinary_and_delayed_cues_use_separate_histories_and_recall_windows():
    roles = case_branches({"ucs": "U__up", "cs": "C__down"})
    windows = ("baseline", "train", "wash", "probe", "postprobe", "late")
    branches = {role:{"windows":{"engine":{w:{"R":{"mean":1., "minimum":1., "maximum":1.}}
                                            for w in windows}}} for role in roles}
    def set_mean(role, window, value):
        branches[role]["windows"]["engine"][window]["R"] = dict(mean=value, minimum=value, maximum=value)
    for role in roles:
        if role.startswith(("ucs_", "paired_")):
            set_mean(role, "train", 3.)
    set_mean("paired_normal", "probe", 3.)
    set_mean("paired_normal", "postprobe", 2.2)
    set_mean("paired_delayed", "postprobe", 4.)
    set_mean("paired_delayed", "late", 2.)
    score = response_score(branches, "engine", "R")
    assert score["normal"]["cue_effects"]["paired"]["value"] == 2.
    assert score["normal"]["recall"]["cue_increment_after_withdrawal"]["value"] == pytest.approx(1.2)
    assert score["normal"]["recall"]["category"] == "retained_half"
    assert score["delayed"]["cue_effects"]["paired"]["value"] == 3.
    assert score["delayed"]["recall"]["cue_increment_after_withdrawal"]["value"] == 1.
    assert score["delayed"]["recall"]["category"] == "below_half"


def test_complete_candidate_inventory_preserves_every_eligible_ucs_and_distinct_identity():
    count, assessments, no_candidates = 0, 0, []
    catalog = json.loads((ROOT/"models/catalog.json").read_text())["models"]
    for entry in catalog:
        reference = json.loads((ROOT/"results/catalog-memory"/f'{entry["biomodel_id"]}.json').read_text())
        plans = candidate_plans(reference)
        count += len(plans)
        if not plans:
            no_candidates.append(entry["network"])
        for plan in plans.values():
            u, c = (reference["cases"][plan[k]]["input"] for k in ("ucs", "cs"))
            assert len(set(plan["responses"])) == len(plan["responses"])
            for response in plan["responses"]:
                assert len({u,c,response}) == 3
                assessments += 1
    assert (count, assessments) == (4208,13080)
    assert no_candidates == [3,6,14,17,33]
