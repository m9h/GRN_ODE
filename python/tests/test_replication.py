from pathlib import Path
import hashlib
import json

import libsbml
import numpy as np
import pytest
import importlib.util
from scipy.io import loadmat

from grn_memory import Phase, regulation, retained, simulate
from grn_memory.experiments import association_experiment, retention_experiment
from grn_memory.simulation import model_info
from grn_memory.suite import compare

ROOT = Path(__file__).resolve().parents[1]
ENGINES = ["roadrunner", "copasi"]
if importlib.util.find_spec("jaxkineticmodel") is not None:
    ENGINES.append("jaxkineticmodel")


@pytest.fixture
def decay(tmp_path):
    # Two-litre compartment distinguishes concentrations from amounts.
    doc = libsbml.SBMLDocument(3, 2)
    m = doc.createModel()
    m.setId("decay")
    m.setSubstanceUnits("mole")
    m.setVolumeUnits("litre")
    m.setTimeUnits("second")
    m.setExtentUnits("mole")
    c = m.createCompartment()
    c.setId("cell")
    c.setSize(2)
    c.setSpatialDimensions(3)
    c.setConstant(True)
    s = m.createSpecies()
    s.setId("A")
    s.setCompartment("cell")
    s.setInitialAmount(2)
    s.setHasOnlySubstanceUnits(False)
    s.setConstant(False)
    s.setBoundaryCondition(False)
    r = m.createReaction()
    r.setId("loss")
    r.setReversible(False)
    sr = r.createReactant()
    sr.setSpecies("A")
    sr.setStoichiometry(1)
    sr.setConstant(True)
    law = r.createKineticLaw()
    law.setMath(libsbml.parseL3Formula("cell * A"))
    path = tmp_path / "decay.xml"
    libsbml.writeSBMLToFile(doc, str(path))
    return path


@pytest.mark.parametrize("engine", ENGINES)
def test_reset_timing_and_concentration_units(decay, engine):
    trace = simulate(decay, [Phase("baseline", .2), Phase("on", .3, {"A": 10}),
                             Phase("off", .2)], engine=engine)
    baseline = trace[trace.phase == "baseline"]
    np.testing.assert_allclose(baseline.A, np.exp(-baseline.time), rtol=2e-7)
    on = trace[trace.phase == "on"]
    # First chunk unforced; boundaries overwritten by the following reset chunk.
    expected = np.concatenate([np.exp(-np.arange(20, 30)*.01),
                               10*np.exp(-np.arange(10)*.01),
                               10*np.exp(-np.arange(11)*.01)])
    np.testing.assert_allclose(on.A, expected, rtol=2e-7)
    off = trace[trace.phase == "off"]
    np.testing.assert_allclose(off.A, 10*np.exp(-(.1+off.time-.5)), rtol=2e-7)


@pytest.mark.parametrize("engine", ENGINES)
def test_drug_script_boundary_resets(decay, engine):
    trace = simulate(decay, [Phase("on", .2, {"A": 10}, True, True), Phase("off", .1)], engine=engine)
    assert trace.iloc[0].A == pytest.approx(10)
    assert trace[trace.phase == "on"].iloc[-1].A == pytest.approx(10*np.exp(-.1))
    assert trace[trace.phase == "off"].iloc[0].A == pytest.approx(10)


@pytest.mark.parametrize("baseline,on,reference,expected", [
    ([1], [2], [1], 1), ([2], [1], [2], -1), ([1], [3], [2], 0),
    ([0], [0], [0], 0), ([1], [1.99], [1], 0),
])
def test_regulation(baseline, on, reference, expected):
    assert regulation(baseline, on, reference) == expected


@pytest.mark.parametrize("baseline,on,off,direction,expected", [
    ([1], [3], [2], 1, True), ([1], [3], [1.99], 1, False),
    ([3], [1], [2], -1, True), ([3], [1], [2.01], -1, False),
])
def test_memory_failure_is_boolean(baseline, on, off, direction, expected):
    result = retained(baseline, on, off, direction)
    assert result is expected  # In MATLAB 9999 ~= 0 incorrectly succeeds.


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_invalid_results_rejected(bad):
    with pytest.raises(ValueError):
        regulation([1], [bad], [1])


@pytest.mark.parametrize("number,network", [(10, 7), (26, 15), (27, 16), (29, 18), (31, 19)])
def test_saved_matlab_initial_state_matches_sbml(number, network):
    path = ROOT / "models" / f"BIOMD{number:010}.xml"
    manifest = json.loads((ROOT / "models" / "manifest.json").read_text())
    source = next(entry for entry in manifest if entry["file"] == path.name)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]
    dynamic = model_info(path)[1]
    trace = simulate(path, [Phase("initial", .01)])
    saved = loadmat(ROOT.parent / "forST.mat", simplify_cells=True)["Bin_Init_x0"][network-1]
    np.testing.assert_array_equal(trace.iloc[0][dynamic].to_numpy(dtype=float), saved)


def test_published_memory_and_no_memory():
    path = ROOT / "models" / "BIOMD0000000031.xml"
    _, positive = retention_experiment(path, "Mpp", "Mp", 1)
    _, negative = retention_experiment(path, "Mp", "Mpp", -1)
    assert positive["ucs_memory"] is True
    assert negative["ucs_memory"] is False


def test_associative_recall_and_sham_control():
    path = ROOT / "models" / "BIOMD0000000026.xml"
    _, positive = association_experiment(path, "M_MKP3", 1, "M", -1, "Mp_MAPKK")
    _, drift = association_experiment(path, "M_MKP3", -1, "Mp_MKP3_dep", -1, "Mpp")
    assert positive["pretest_passed"]
    assert positive["associative_memory"]
    assert positive["long_recall"]
    assert positive["probe_differs_from_paired_sham"]
    assert drift["associative_memory"]
    assert not drift["probe_differs_from_paired_sham"]


def test_cross_engine_reset_protocol(decay):
    phases = [Phase("on", .4, {"A": 5}), Phase("off", .3)]
    a, b = [simulate(decay, phases, engine=e) for e in ["roadrunner", "copasi"]]
    assert compare(a, b)["passed"]


@pytest.mark.parametrize("phase", [Phase("bad", .15, {"A": 1}), Phase("bad", .2, {"missing": 1}),
                                    Phase("bad", .2, {"A": -1})])
def test_invalid_protocol_rejected(decay, phase):
    with pytest.raises(ValueError):
        simulate(decay, [phase])
