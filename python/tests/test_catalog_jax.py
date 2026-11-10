"""Check every observable, including derived species and non-species rules."""

import numpy as np
import pytest

from grn_memory.catalog_jax import observable_trajectory
from grn_memory.catalog_validation import comparison, inspect_model, native_trajectory
from test_native_kinetics import sbml_file


def test_jax_observables_preserve_symbol_units_and_rule_dependencies(tmp_path):
    pytest.importorskip("jaxkineticmodel")
    import jax
    import jax.numpy as jnp
    from jaxkineticmodel.load_sbml.sbml_model import SBMLModel

    path = sbml_file(tmp_path, '''
<listOfSpecies>
<species id="A" compartment="cell" initialAmount="2" boundaryCondition="false" constant="false" hasOnlySubstanceUnits="true"/>
<species id="D" compartment="cell" boundaryCondition="false" constant="false" hasOnlySubstanceUnits="true"/>
<species id="B" compartment="cell" initialConcentration="3" boundaryCondition="true" constant="true" hasOnlySubstanceUnits="false"/>
</listOfSpecies>
<listOfParameters><parameter id="q" constant="false"/></listOfParameters>
<listOfRules>
<assignmentRule variable="D"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><cn>2</cn><ci>A</ci></apply></math></assignmentRule>
<assignmentRule variable="q"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><plus/><ci>D</ci><csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">time</csymbol></apply></math></assignmentRule>
</listOfRules>
<listOfReactions><reaction id="decay" reversible="false">
<listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
<kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>A</ci></math></kineticLaw>
</reaction></listOfReactions>
''')
    model = SBMLModel(str(path))
    solve = model.get_kinetic_model()
    solve.dt0 = 1e-4
    times = np.linspace(0, 2, 21)
    values = jax.jit(solve)(jnp.asarray(times), model.y0, model.parameters)
    trace = observable_trajectory(model, solve, times, values, inspect_model(path)["observables"])
    np.testing.assert_allclose(trace.A, np.exp(-times), rtol=1e-7)
    np.testing.assert_allclose(trace.D, 2*np.exp(-times), rtol=1e-7)
    np.testing.assert_array_equal(trace.B, np.full(len(times), 3.))
    np.testing.assert_allclose(trace.q, 4*np.exp(-times)+times, rtol=1e-7)
    assert model.species_names == ["A"]
    for engine in ("roadrunner", "copasi"):
        assert comparison(trace, native_trajectory(path, times, engine))["passed"]
