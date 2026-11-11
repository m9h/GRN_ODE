"""Analytic checks for the optional arbitrary-precision reaction adapter."""

import libsbml
import numpy as np
import pytest

pytest.importorskip("heyoka")

from grn_memory.taylor_reference import taylor_trajectory


def decay(tmp_path, stoichiometry=1.):
    document = libsbml.SBMLDocument(3, 2)
    model = document.createModel()
    model.setId("precision_decay")
    cell = model.createCompartment()
    cell.setId("cell"); cell.setSize(2.); cell.setConstant(True); cell.setSpatialDimensions(3)
    for name, amount, boundary in (("A", False, False), ("B", True, False), ("C", False, True)):
        species = model.createSpecies()
        species.setId(name); species.setCompartment("cell")
        species.setHasOnlySubstanceUnits(amount); species.setBoundaryCondition(boundary)
        species.setConstant(False)
        if amount:
            species.setInitialAmount(2.)
        else:
            species.setInitialConcentration(3. if boundary else 1.)
    for name in ("A", "B"):
        reaction = model.createReaction()
        reaction.setId("decay_"+name); reaction.setReversible(False)
        reactant = reaction.createReactant()
        reactant.setSpecies(name); reactant.setStoichiometry(stoichiometry); reactant.setConstant(True)
        law = reaction.createKineticLaw()
        law.setMath(libsbml.parseL3Formula("cell*A" if name == "A" else "B"))
    path = tmp_path/"decay.xml"
    libsbml.writeSBMLToFile(document, str(path))
    return path


def test_complete_state_and_symbol_units_survive_all_resets(tmp_path):
    path = decay(tmp_path)
    original = path.read_bytes()
    times = np.array([0., .39, .41, .79, .81, 1.19, 1.21, 1.6, 2.])
    trains = [dict(start=.4, stop=1.6, values={"A": 4.}, interval=.4),
              dict(start=.4, stop=1.2, values={"B": 4.}, interval=.4, include_start=True, include_stop=True)]
    evidence = {}
    names, values = taylor_trajectory(path, times, trains, evidence=evidence)
    for column, onset in ((0, .8), (1, .4)):
        last = np.where(times > 1.2, 1.2, np.where(times > .8, .8, np.where(times > onset, onset, 0.)))
        expected = np.where(last > 0, 4., 1.)*np.exp(-(times-last))
        np.testing.assert_allclose(values[:, column], expected, rtol=2e-14, atol=2e-14)
    assert names == ["A", "B", "C"]
    np.testing.assert_array_equal(values[:, 2], np.full(len(times), 3.))
    assert evidence["completed"] and evidence["performed_resets"] == 3
    assert evidence["train_reset_counts"] == [2, 3] and evidence["completed_segments"] == 4
    assert path.read_bytes() == original


def test_fractional_stoichiometry_is_retained(tmp_path):
    times = np.linspace(0., 2., 31)
    _, values = taylor_trajectory(decay(tmp_path, .25), times)
    for column in (0, 1):
        np.testing.assert_allclose(values[:, column], np.exp(-.25*times), rtol=1e-14, atol=1e-14)


def test_boundary_species_cannot_be_an_input(tmp_path):
    with pytest.raises(ValueError, match="Only independent"):
        taylor_trajectory(decay(tmp_path), [0., 2.], [dict(start=.4, stop=1.2, interval=.4, values={"C": 4.})])


@pytest.mark.parametrize("feature", ["event", "assignment", "rate"])
def test_unsupported_semantics_are_rejected(tmp_path, feature):
    path = decay(tmp_path)
    document = libsbml.readSBMLFromFile(str(path))
    model = document.getModel()
    if feature == "event":
        event = model.createEvent(); event.setUseValuesFromTriggerTime(True)
        trigger = event.createTrigger(); trigger.setInitialValue(False); trigger.setPersistent(True)
        trigger.setMath(libsbml.parseL3Formula("time > 1"))
        assignment = event.createEventAssignment(); assignment.setVariable("A")
        assignment.setMath(libsbml.parseL3Formula("2"))
    else:
        rule = model.createAssignmentRule() if feature == "assignment" else model.createRateRule()
        rule.setVariable("C"); rule.setMath(libsbml.parseL3Formula("1"))
    libsbml.writeSBMLToFile(document, str(path))
    with pytest.raises(ValueError, match="does not support"):
        taylor_trajectory(path, [0., 2.])


def test_ambiguous_discontinuity_observation_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="ambiguous reset"):
        taylor_trajectory(decay(tmp_path), [0., .8, 2.], [dict(start=.4, stop=1.2, interval=.4, values={"A": 4.})])


def test_overlapping_resets_cannot_silently_overwrite(tmp_path):
    train = dict(start=.4, stop=1.2, interval=.4, values={"A": 4.})
    with pytest.raises(ValueError, match="Conflicting simultaneous"):
        taylor_trajectory(decay(tmp_path), [0., 2.], [train, train])
