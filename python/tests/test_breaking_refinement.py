"""Refinement preserves source semantics and never loosens a tolerance."""

from copy import deepcopy
import json

import pytest

from scripts import diagnose_breaking_refinement as diagnostic


SOURCE = diagnostic.ROOT/"results/catalog-breaking-linux-26/shard-3/BIOMD0000000664.json"
MODEL = diagnostic.ROOT/"models/BIOMD0000000664.xml"


def test_tiny_state_absolute_tolerance_is_tightened():
    original = {"rtol": 1e-12, "atol": 1e-18}
    requests = diagnostic.refinement_requests(original)
    assert requests == {"original": original, "tight": {"rtol": 1e-13, "atol": 1e-19},
                        "tighter": {"rtol": 5e-14, "atol": 5e-20}}
    assert original == {"rtol": 1e-12, "atol": 1e-18}


def test_goldbeter_refinement_retains_its_published_requests():
    requests = diagnostic.refinement_requests({"rtol": 1e-12, "atol": 1e-14})
    assert requests["tight"] == {"rtol": 1e-13, "atol": 1e-15}
    assert requests["tighter"] == {"rtol": 5e-14, "atol": 5e-16}


@pytest.mark.parametrize("settings", [{"rtol": 1e-12, "atol": 0}, {"rtol": float("nan"), "atol": 1e-18},
                                     {"rtol": 1e-12, "atol": 5e-324}, {"rtol": 1e-12}])
def test_invalid_or_underflowing_requests_are_rejected(settings):
    with pytest.raises(ValueError):
        diagnostic.refinement_requests(settings)


def test_complete_partition_failures_retain_original_encoding():
    before = MODEL.read_bytes()
    evidence = diagnostic.capture(SOURCE)
    assert len(evidence["failed_branches"]) == 14
    assert all(b["sample_count"] == 221001 and b["specification"]["stop"] == 2210
               for b in evidence["failed_branches"])
    assert diagnostic.trajectory_for(evidence["original_report"], MODEL) is diagnostic.yoon_trajectory
    assert MODEL.read_bytes() == before


@pytest.mark.parametrize("key", ["method", "sha256"])
def test_changed_encoding_cannot_be_used(key):
    original = json.loads(SOURCE.read_text())
    original["configuration"]["timed_drive_encoding"][key] = "changed"
    with pytest.raises(ValueError, match="encoding differs"):
        diagnostic.trajectory_for(original, MODEL)


def test_native_and_delay_encodings_remain_distinct():
    original = json.loads(SOURCE.read_text())
    native = deepcopy(original)
    native["configuration"]["timed_drive_encoding"] = None
    assert diagnostic.trajectory_for(native, MODEL) is diagnostic.protocol_trajectory
    native["engines"] = ["method_of_steps", "jitcdde"]
    with pytest.raises(NotImplementedError, match="native ODE engines"):
        diagnostic.trajectory_for(native, MODEL)
