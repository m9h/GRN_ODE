"""Analytic intervention checks, independent of the implementation's event logic."""

import libsbml
import numpy as np
import pytest

from grn_memory.native_protocols import ResetTrain, encode_protocol, intervention_targets, protocol_trajectory
from test_native_kinetics import sbml_file


def decay_model(tmp_path):
    path = sbml_file(tmp_path, '''
<listOfSpecies>
<species id="A" compartment="cell" initialConcentration="1" boundaryCondition="false" constant="false" hasOnlySubstanceUnits="false"/>
<species id="B" compartment="cell" initialAmount="2" boundaryCondition="false" constant="false" hasOnlySubstanceUnits="true"/>
<species id="D" compartment="cell" initialConcentration="3" boundaryCondition="true" constant="false" hasOnlySubstanceUnits="false"/>
<species id="C" compartment="cell" initialConcentration="3" boundaryCondition="true" constant="true" hasOnlySubstanceUnits="false"/>
</listOfSpecies>
<listOfParameters><parameter id="p" value="1" constant="false"/><parameter id="k" value="1" constant="false"/></listOfParameters>
<listOfRules>
<rateRule variable="p"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><minus/><ci>p</ci></apply></math></rateRule>
<assignmentRule variable="D"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/><ci>A</ci><ci>p</ci><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol></apply></math></assignmentRule>
</listOfRules>
<listOfReactions>
<reaction id="decayA" reversible="false"><listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
<kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>cell</ci><ci>k</ci><ci>A</ci></apply></math></kineticLaw></reaction>
<reaction id="decayB" reversible="false"><listOfReactants><speciesReference species="B" stoichiometry="1" constant="true"/></listOfReactants>
<kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k</ci><ci>B</ci></apply></math></kineticLaw></reaction>
</listOfReactions>
<listOfEvents><event id="switch" useValuesFromTriggerTime="true">
<trigger initialValue="false" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><geq/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>1</cn></apply></math></trigger>
<listOfEventAssignments><eventAssignment variable="k"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></eventAssignment></listOfEventAssignments>
</event></listOfEvents>
''')
    return path


@pytest.mark.parametrize("engine", ["roadrunner", "copasi"])
def test_resets_preserve_native_time_rules_and_events(tmp_path, engine):
    path = decay_model(tmp_path)
    # Avoid exact discontinuities: assert both sides and the unforced final block.
    times = np.array([0, .4, .79, .81, .99, 1.01, 1.19, 1.21, 1.6, 2.])
    train = ResetTrain(.4, 1.6, {"A": 4., "B": 4.}, interval=.4)
    result = protocol_trajectory(path, times, [train], engine)
    accumulated_rate = lambda t: np.minimum(t, 1) + 2*np.maximum(t-1, 0)
    last = np.where(times > 1.2, 1.2, np.where(times > .8, .8, 0))
    expected = np.where(last > 0, 4, 1)*np.exp(-(accumulated_rate(times)-accumulated_rate(last)))
    np.testing.assert_allclose(result.A, expected, rtol=1e-8, atol=1e-9)
    np.testing.assert_allclose(result.B, expected, rtol=1e-8, atol=1e-9)
    np.testing.assert_allclose(result.p, np.exp(-times), rtol=1e-8, atol=1e-9)
    np.testing.assert_allclose(result.D, expected+np.exp(-times)+times, rtol=1e-8, atol=1e-9)
    np.testing.assert_array_equal(result.k, np.where(times < 1, 1, 2))


@pytest.mark.parametrize("engine", ["roadrunner", "copasi"])
def test_rate_parameter_resets_and_explicit_endpoint_policy(tmp_path, engine):
    path = decay_model(tmp_path)
    times = np.array([0, .39, .41, .79, .81, 1.19, 1.21, 2.])
    train = ResetTrain(.4, 1.2, {"p": 3.}, interval=.4, include_start=True, include_stop=True)
    result = protocol_trajectory(path, times, [train], engine)
    last = np.where(times > 1.2, 1.2, np.where(times > .8, .8, np.where(times > .4, .4, 0)))
    expected = np.where(last > 0, 3, 1)*np.exp(-(times-last))
    np.testing.assert_allclose(result.p, expected, rtol=1e-8, atol=1e-9)


def test_independent_targets_and_conflicts(tmp_path):
    path = decay_model(tmp_path)
    allowed, excluded = intervention_targets(path)
    assert allowed == {"A": "concentration", "B": "concentration", "p": "rate-rule parameter"}
    assert excluded == {"D": "assignment rule", "C": "constant"}
    with pytest.raises(ValueError, match="independent"):
        encode_protocol(path, [ResetTrain(1, 2, {"D": 3})])
    with pytest.raises(ValueError, match="Conflicting"):
        encode_protocol(path, [ResetTrain(1, 2, {"A": 3})]*2)
    before = path.read_bytes()
    doc = libsbml.readSBMLFromString(encode_protocol(path, [ResetTrain(1, 2, {"A": 3})]))
    assert doc.getModel().getNumEvents() == 2
    assert path.read_bytes() == before


def test_unicode_model_metadata_survives_solver_locale_changes(tmp_path):
    path = decay_model(tmp_path)
    doc = libsbml.readSBML(str(path))
    doc.getModel().setName("François – concentration model")
    libsbml.writeSBMLToFile(doc, str(path))
    for engine in ("copasi", "roadrunner", "copasi"):
        result = protocol_trajectory(path, [0., 1.01, 2.], [ResetTrain(.4, 1.2, {"A": 3.}, interval=.4)], engine)
        assert np.isfinite(result.A).all()


