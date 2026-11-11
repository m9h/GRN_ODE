"""Check the independent stiff reference against analytic and native solutions."""

import libsbml
import numpy as np
import pytest

from grn_memory.catalog_validation import comparison
from grn_memory.native_protocols import ResetTrain, protocol_trajectory
from grn_memory.scipy_reference import scipy_protocol_trajectory
from test_jax_protocols import autonomous_decay
from test_native_protocols import decay_model


@pytest.mark.parametrize("method", ["Radau", "BDF"])
def test_complete_state_units_and_observables_through_resets(tmp_path, method):
    pytest.importorskip("jaxkineticmodel")
    path = autonomous_decay(tmp_path)
    original = path.read_bytes()
    times = np.array([0., .39, .41, .79, .81, 1.19, 1.21, 1.6, 2.])
    trains = [ResetTrain(.4, 1.6, {"A": 4.}, interval=.4),
              ResetTrain(.4, 1.2, {"B": 4.}, interval=.4, include_start=True, include_stop=True)]
    evidence, interval_ends = {}, []
    trace = scipy_protocol_trajectory(path, times, trains, method=method, evidence=evidence,
        progress=lambda row: interval_ends.append(row["last_interval"][1]))
    for species, onset in (("A", .8), ("B", .4)):
        last = np.where(times > 1.2, 1.2, np.where(times > .8, .8,
                        np.where(times > onset, onset, 0.)))
        expected = np.where(last > 0, 4., 1.)*np.exp(-(times-last))
        np.testing.assert_allclose(trace[species], expected, rtol=1e-8, atol=1e-9)
    np.testing.assert_allclose(trace.D, trace.A+1, rtol=0, atol=1e-12)
    np.testing.assert_array_equal(trace.C, np.full(len(times), 3.))
    np.testing.assert_allclose(interval_ends, [.4, .8, 1.2, 2.])
    assert evidence["completed"] and evidence["completed_segments"] == 4
    assert evidence["performed_resets"] == 3 and evidence["train_reset_counts"] == [2, 3]
    assert evidence["nfev"] > 0 and evidence["njev"] > 0 and evidence["nlu"] > 0
    for engine in ("roadrunner", "copasi"):
        assert comparison(trace, protocol_trajectory(path, times, trains, engine))["passed"]
    assert path.read_bytes() == original


def test_source_edit_invalidates_derivative_cache(tmp_path):
    pytest.importorskip("jaxkineticmodel")
    path = autonomous_decay(tmp_path)
    times = np.array([0., 1., 2.])
    first = scipy_protocol_trajectory(path, times, [])
    doc = libsbml.readSBML(str(path))
    doc.getModel().getParameter("k").setValue(2.)
    libsbml.writeSBMLToFile(doc, str(path))
    second = scipy_protocol_trajectory(path, times, [])
    np.testing.assert_allclose(first.A, np.exp(-times), rtol=1e-8)
    np.testing.assert_allclose(second.A, np.exp(-2*times), rtol=1e-8)


def test_native_events_are_not_dropped(tmp_path):
    with pytest.raises(NotImplementedError, match="Native events"):
        scipy_protocol_trajectory(decay_model(tmp_path), [0., 1., 2.], [])


@pytest.mark.parametrize("times,trains,message", [
    ([0., float("nan"), 2.], [], "Finite increasing"),
    ([0., .8, 2.], [ResetTrain(.4, 1.2, {"A": 4.}, interval=.4)], "ambiguous reset"),
])
def test_invalid_observation_grids_are_rejected(tmp_path, times, trains, message):
    with pytest.raises(ValueError, match=message):
        scipy_protocol_trajectory(autonomous_decay(tmp_path), times, trains)
