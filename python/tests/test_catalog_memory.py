"""Classification must not turn numerical zero tails into memory evidence."""

import numpy as np
import pandas as pd

from grn_memory.catalog_memory import classification_agreement, scores
from grn_memory.native_protocols import ResetTrain, sample_times


def test_opposite_roundoff_tails_have_unresolved_memory_labels():
    times = np.arange(1301)/100
    def trace(tail):
        return pd.DataFrame({"time": times, "R": np.where(times == 0, 1., tail)})
    control = trace(-1e-30)
    by_engine = {"a": scores(trace(5e-24), control, ["S", "R"], "S", 1),
                 "b": scores(trace(-1e-22), control, ["S", "R"], "S", 1)}
    assert by_engine["a"]["R"]["paper_like_ucs_memory"] is False
    assert by_engine["b"]["R"]["paper_like_ucs_memory"] is True
    assert all(result["R"]["matched_retention"] is None for result in by_engine.values())
    raw, resolved, unresolved = classification_agreement(by_engine, ["a", "b"])
    assert raw and not resolved and unresolved == ["R"]


def test_resolved_response_disagreement_remains_a_failure():
    times = np.arange(1301)/100
    control = pd.DataFrame({"time": times, "R": np.ones(len(times))})
    def treated(level):
        return pd.DataFrame({"time": times, "R": np.where(times > 1, level, 1.)})
    by_engine = {"a": scores(treated(5.), control, ["S", "R"], "S", 1),
                 "b": scores(treated(.1), control, ["S", "R"], "S", 1)}
    _, resolved, unresolved = classification_agreement(by_engine, ["a", "b"])
    assert "R" in resolved and not unresolved


def test_sample_times_record_post_reset_offsets_without_moving_other_samples():
    train = ResetTrain(.4, 1.6, {"A": 4.}, interval=.4)
    times = sample_times(2., .01, [train])
    assert times[80] == .8+1e-6
    assert np.isclose(times[120], 1.2+1e-6, rtol=0, atol=1e-15)
    assert times[79] == .79 and times[160] == 1.6
    assert np.all(np.diff(times) > 0)
