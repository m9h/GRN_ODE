"""Independent analytic checks for native SBML features in the 35-model suite."""

import numpy as np
import pytest

from grn_memory.catalog_validation import native_trajectory


def sbml_file(tmp_path, body):
    path = tmp_path / "analytic.xml"
    path.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2">
<model id="analytic">
<listOfCompartments><compartment id="cell" size="2" constant="true" spatialDimensions="3"/></listOfCompartments>
''' + body + "</model></sbml>")
    return path


@pytest.mark.parametrize("engine", ["roadrunner", "copasi"])
def test_rate_parameter_assignment_species_and_time(tmp_path, engine):
    path = sbml_file(tmp_path, '''
<listOfSpecies>
<species id="A" compartment="cell" initialConcentration="2" boundaryCondition="true" constant="false" hasOnlySubstanceUnits="false"/>
<species id="B" compartment="cell" initialAmount="6" boundaryCondition="true" constant="true" hasOnlySubstanceUnits="false"/>
</listOfSpecies>
<listOfParameters><parameter id="p" value="1" constant="false"/><parameter id="q" value="1" constant="false"/></listOfParameters>
<listOfRules>
<rateRule variable="p"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><minus/><ci>p</ci></apply></math></rateRule>
<assignmentRule variable="A"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><cn>2</cn><ci>p</ci></apply></math></assignmentRule>
<assignmentRule variable="q"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/><cn>1</cn><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol></apply></math></assignmentRule>
</listOfRules>
''')
    times = np.linspace(0, 2, 21)
    trace = native_trajectory(path, times, engine)
    np.testing.assert_allclose(trace.p, np.exp(-times), rtol=1e-8, atol=1e-10)
    np.testing.assert_allclose(trace.A, 2*np.exp(-times), rtol=1e-8, atol=1e-10)
    np.testing.assert_allclose(trace.B, 3, rtol=0, atol=1e-12)
    np.testing.assert_allclose(trace.q, 1+times, rtol=0, atol=1e-10)


@pytest.mark.parametrize("engine", ["roadrunner", "copasi"])
def test_event_changes_parameter_and_subsequent_kinetics(tmp_path, engine):
    path = sbml_file(tmp_path, '''
<listOfSpecies><species id="A" compartment="cell" initialConcentration="1" boundaryCondition="false" constant="false" hasOnlySubstanceUnits="false"/></listOfSpecies>
<listOfParameters><parameter id="k" value="1" constant="false"/></listOfParameters>
<listOfReactions><reaction id="decay" reversible="false">
<listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
<kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>cell</ci><ci>k</ci><ci>A</ci></apply></math></kineticLaw>
</reaction></listOfReactions>
<listOfEvents><event id="switch" useValuesFromTriggerTime="true">
<trigger initialValue="false" persistent="true"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><geq/><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol><cn>1</cn></apply></math></trigger>
<listOfEventAssignments><eventAssignment variable="k"><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>2</cn></math></eventAssignment></listOfEventAssignments>
</event></listOfEvents>
''')
    times = np.array([0, .5, .99, 1.01, 1.5, 2.])
    trace = native_trajectory(path, times, engine)
    expected = np.exp(-np.minimum(times, 1)-2*np.maximum(times-1, 0))
    np.testing.assert_allclose(trace.A, expected, rtol=1e-8, atol=1e-10)
    np.testing.assert_array_equal(trace.k, np.where(times < 1, 1, 2))


def test_comparison_does_not_accept_nonfinite_or_misaligned_values():
    import pandas as pd
    from grn_memory.catalog_validation import comparison
    reference = pd.DataFrame({"time": [0., 1.], "A": [1., .5]})
    invalid = reference.copy()
    invalid.loc[1, "A"] = np.nan
    with pytest.raises(ValueError, match="Non-finite"):
        comparison(reference, invalid)
    invalid = reference.copy()
    invalid.loc[1, "time"] = 2
    with pytest.raises(AssertionError):
        comparison(reference, invalid)
