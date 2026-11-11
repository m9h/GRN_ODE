"""Analytic and independent-engine checks for complete-state JAX resets."""

import libsbml
import numpy as np
import pytest

from grn_memory.catalog_validation import comparison
from grn_memory.jax_protocols import jax_protocol_trajectory, supported_model
from grn_memory.native_protocols import ResetTrain, protocol_trajectory
from test_native_protocols import decay_model


def autonomous_decay(tmp_path):
    path = decay_model(tmp_path)
    doc = libsbml.readSBML(str(path))
    model = doc.getModel()
    model.removeEvent(0)
    model.removeRule("p")
    model.getParameter("p").setConstant(True)
    model.getParameter("k").setConstant(True)
    model.getRuleByVariable("D").setMath(libsbml.parseL3Formula("A + p"))
    libsbml.writeSBMLToFile(doc, str(path))
    return path


@pytest.mark.parametrize("solver,root_finder", [
    ("Kvaerno3", "VeryChord"), ("Kvaerno4", "VeryChord"),
    ("Kvaerno5", "VeryChord"), ("Kvaerno5", "Newton"),
])
def test_resets_carry_unforced_states_amounts_and_derived_observables(tmp_path, solver, root_finder):
    pytest.importorskip("jaxkineticmodel")
    path = autonomous_decay(tmp_path)
    original = path.read_bytes()
    times = np.array([0., .39, .41, .79, .81, 1.19, 1.21, 1.6, 2.])
    trains = [ResetTrain(.4, 1.6, {"A": 4.}, interval=.4),
              ResetTrain(.4, 1.2, {"B": 4.}, interval=.4, include_start=True, include_stop=True)]
    evidence = {}
    trace = jax_protocol_trajectory(path, times, trains, solver=solver,
        root_finder=root_finder, root_find_max_steps=20 if root_finder == "Newton" else 10, evidence=evidence)
    for species, onset in (("A", .8), ("B", .4)):
        last = np.where(times > 1.2, 1.2, np.where(times > .8, .8,
                        np.where(times > onset, onset, 0.)))
        expected = np.where(last > 0, 4., 1.)*np.exp(-(times-last))
        np.testing.assert_allclose(trace[species], expected, rtol=1e-8, atol=1e-9)
    np.testing.assert_allclose(trace.D, trace.A+1, rtol=0, atol=1e-12)
    np.testing.assert_array_equal(trace.C, np.full(len(times), 3.))
    assert evidence["performed_resets"] == 3
    assert evidence["train_reset_counts"] == [2, 3]
    assert evidence["completed_segments"] == 4 and evidence["completed"]
    assert evidence["absolute_time_preserved"]
    assert evidence["root_finder"] == root_finder
    for engine in ("roadrunner", "copasi"):
        reference = protocol_trajectory(path, times, trains, engine)
        assert comparison(reference, trace)["passed"]
    assert path.read_bytes() == original


def test_changed_source_invalidates_compiled_model(tmp_path):
    pytest.importorskip("jaxkineticmodel")
    path = autonomous_decay(tmp_path)
    first = jax_protocol_trajectory(path, [0., 1., 2.], [])
    doc = libsbml.readSBML(str(path))
    doc.getModel().getParameter("k").setValue(2.)
    libsbml.writeSBMLToFile(doc, str(path))
    second = jax_protocol_trajectory(path, [0., 1., 2.], [])
    np.testing.assert_allclose(first.A, np.exp(-np.array([0., 1., 2.])), rtol=1e-8)
    np.testing.assert_allclose(second.A, np.exp(-2*np.array([0., 1., 2.])), rtol=1e-8)


@pytest.mark.parametrize("feature, message", [
    ("event", "Native events"), ("rate", "Rate and algebraic"),
    ("delay", "history-preserving"), ("time", "Time-dependent"),
    ("volume", "positive-volume"), ("initial", "Initial assignments"),
    ("conversion", "conversion factors"),
])
def test_unsupported_semantics_fail_explicitly(tmp_path, feature, message):
    path = autonomous_decay(tmp_path)
    doc = libsbml.readSBML(str(path))
    model = doc.getModel()
    if feature == "event":
        native = libsbml.readSBML(str(decay_model(tmp_path)))
        model.addEvent(native.getModel().getEvent(0).clone())
        model.getParameter("k").setConstant(False)
    elif feature == "rate":
        rule = model.createRateRule()
        rule.setVariable("p")
        rule.setMath(libsbml.parseL3Formula("-p"))
        model.getParameter("p").setConstant(False)
    elif feature in ("delay", "time"):
        expression = "delay(A, 1)" if feature == "delay" else "A + time"
        model.getRuleByVariable("D").setMath(libsbml.parseL3Formula(expression))
    elif feature == "volume":
        model.getCompartment("cell").setConstant(False)
    elif feature == "initial":
        initial = model.createInitialAssignment()
        initial.setSymbol("A")
        initial.setMath(libsbml.parseL3Formula("p"))
    else:
        model.setConversionFactor("p")
    libsbml.writeSBMLToFile(doc, str(path))
    with pytest.raises(NotImplementedError, match=message):
        supported_model(path)


@pytest.mark.parametrize("times,trains,message", [
    ([0., float("nan"), 2.], [], "Finite increasing"),
    ([0., .8, 2.], [ResetTrain(.4, 1.2, {"A": 4.}, interval=.4)], "ambiguous reset"),
    ([0., 1., 2.], [ResetTrain(0., .4, {"A": 4.}, interval=.4, include_start=True)], "strictly inside"),
    ([0., 1., 2.], [ResetTrain(.4, 1.2, {"D": 4.}, interval=.4)], "independent"),
    ([0., 1., 2.], [ResetTrain(.4, 1.2, {"A": -1.}, interval=.4)], "nonnegative"),
    ([0., 1., 2.], [ResetTrain(.4, 1.2, {"A": 4.}, interval=.4)]*2, "Conflicting"),
])
def test_ambiguous_or_invalid_protocol_is_not_integrated(tmp_path, times, trains, message):
    with pytest.raises(ValueError, match=message):
        jax_protocol_trajectory(autonomous_decay(tmp_path), times, trains)
