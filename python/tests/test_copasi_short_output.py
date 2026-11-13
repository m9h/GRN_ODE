"""Instrumentation must preserve both successful output and solver exceptions."""

import numpy as np
import pandas as pd
import pytest

from scripts import diagnose_copasi_short_output as probe


def test_partial_output_is_recorded_without_padding_or_argument_changes(tmp_path, monkeypatch):
    requested = [0., 1., 2., 3.]
    output = pd.DataFrame({"Time": [0., 1.], "A": [1., .5]})
    calls = []
    def original(*args, **kwargs):
        calls.append((args, kwargs))
        return output
    monkeypatch.setattr(probe, "copasi_messages", lambda: "solver stopped early")
    monitor = {}; path = tmp_path/"raw.npz"
    returned = probe.observe_time_course(original, path, monitor, ["Time", "A"], values=requested,
                                         r_tol=1e-12, a_tol=1e-14, max_steps=100000)
    assert returned is output and calls[0][1]["values"] is requested
    assert calls[0][1]["r_tol"] == 1e-12 and calls[0][1]["a_tol"] == 1e-14
    assert calls[0][1]["max_steps"] == 100000
    assert monitor["requested_samples"] == 4 and monitor["shape"] == [2, 2]
    assert monitor["last_row"] == {"Time": 1., "A": .5}
    assert monitor["copasi_messages"] == "solver stopped early"
    with np.load(path, allow_pickle=False) as saved:
        np.testing.assert_array_equal(saved["values"], output.to_numpy())


def test_solver_exception_is_preserved_and_no_trajectory_is_invented(tmp_path, monkeypatch):
    error = RuntimeError("integration failed")
    def original(*args, **kwargs):
        raise error
    monkeypatch.setattr(probe, "copasi_messages", lambda: "convergence failure")
    monitor = {}; path = tmp_path/"raw.npz"
    with pytest.raises(RuntimeError) as caught:
        probe.observe_time_course(original, path, monitor, values=[0., 1.])
    assert caught.value is error and not path.exists()
    assert monitor == {"copasi_messages": "convergence failure"}
