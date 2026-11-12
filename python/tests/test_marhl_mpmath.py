"""The fixed-model reference checks equations and complete reset semantics."""

import numpy as np
import pytest
from copy import deepcopy

mpmath = pytest.importorskip("mpmath")

from grn_memory import marhl_mpmath as reference
from grn_memory.catalog_validation import ROOT


MODEL = ROOT/"models/BIOMD0000000039.xml"


def test_transcribed_rates_match_native_sbml_across_widely_separated_states():
    import roadrunner
    context = mpmath.mp.clone(); context.prec = 128
    rhs, initial = reference.equations(context)
    native = roadrunner.RoadRunner(str(MODEL))
    assert list(native.model.getFloatingSpeciesIds()) == reference.NAMES
    states = [np.array(list(map(float,initial)))]
    states.extend(10.**np.random.default_rng(72).uniform(-6,4,(20,5)))
    for state in states:
        native.model.setFloatingSpeciesConcentrations(state)
        actual = np.array([float(v) for v in rhs(context.mpf(0),list(map(context.mpf,state)))])
        np.testing.assert_allclose(actual,native.getRatesOfChange(),rtol=2e-12,atol=1e-8)
        c,e,m,b,p = rhs(context.mpf(0),list(map(context.mpf,state)))
        scale = max(1,*map(abs,(c,e,m,b,p)))
        assert abs(c+4*e+4*m+b) <= 20*context.eps*scale
        assert b+p == 0


def test_unforced_reference_matches_saved_high_precision_observations():
    saved = np.load(ROOT/"results/catalog-paired-taylor-marhl/untreated_baseline-taylor192.npz")
    selected = saved['times'] <= 2
    before = mpmath.mp.prec
    evidence = {}
    names,values = reference.trajectory(MODEL,saved['times'][selected],evidence=evidence)
    assert names == list(saved['observables']) and mpmath.mp.prec == before
    np.testing.assert_allclose(values,saved['values'][selected],rtol=1e-12,atol=1e-13)
    assert evidence['completed'] and evidence['completed_segments'] == 1 and evidence['performed_resets'] == 0


def test_resets_preserve_absolute_time_and_every_other_state(monkeypatch):
    def equations(context):
        return lambda t,y: [t,t*t,0,0,0],list(map(context.mpf,(0,0,3,4,5)))
    monkeypatch.setattr(reference,'equations',equations)
    times = np.array([0,.09999,.10001,.29999,.30001,.50001,1.])
    train = {'start':.1,'stop':.5,'interval':.2,'include_start':True,'include_stop':True,'values':{'Ca_cyt':10.}}
    evidence = {}
    _,values = reference.trajectory(MODEL,times,[train],evidence=evidence)
    expected = [t*t/2 if t<.1 else 10+(t*t-(.1 if t<.3 else .3 if t<.5 else .5)**2)/2 for t in times]
    np.testing.assert_allclose(values[:,0],expected,rtol=0,atol=1e-13)
    np.testing.assert_allclose(values[:,1],times**3/3,rtol=0,atol=1e-13)
    np.testing.assert_array_equal(values[:,2:],np.tile([3,4,5],(len(times),1)))
    assert evidence['performed_resets']==3 and evidence['completed_segments']==4


def test_a_different_model_cannot_use_the_transcribed_equations(tmp_path):
    path=tmp_path/'model.xml';path.write_bytes(MODEL.read_bytes()+b'\n')
    with pytest.raises(ValueError,match='original BioModel 39'):
        reference.trajectory(path,[0,1])


@pytest.mark.parametrize('trains,times,message',[
    ([{'start':0,'stop':.2,'values':{'Ca_cyt':1}}],[0,.1,1],'ambiguous'),
    ([{'start':0,'stop':.2,'values':{'unknown':1}}],[0,.05,1],'model species'),
    ([{'start':0,'stop':.2,'values':{'Ca_cyt':-1}}],[0,.05,1],'nonnegative'),
    ([{'start':0,'stop':.2,'values':{'Ca_cyt':1}}]*2,[0,.05,1],'Conflicting'),
])
def test_invalid_interventions_are_rejected(trains,times,message):
    with pytest.raises(ValueError,match=message):
        reference.trajectory(MODEL,times,trains)


def test_resume_rejects_incomplete_or_changed_integration_evidence():
    from scripts.diagnose_marhl_mpmath import validate_integration
    times = np.array([0., .09999, .10001, .3])
    trains = [{'start':0., 'stop':.2, 'values':{'Ca_cyt':.4}}]
    request = {'precision':128, 'tolerance':'1e-30', 'degree':32}
    evidence = {}
    reference.trajectory(MODEL,times,trains,**request,evidence=evidence)
    validate_integration(evidence,request,times,trains)
    for key,value in [('performed_resets',0), ('sample_count',3), ('precision_bits',64),
                      ('model_sha256','wrong'), ('absolute_time_preserved',False),
                      ('completed_segments',1), ('train_reset_counts',[0])]:
        altered = deepcopy(evidence)
        altered[key] = value
        with pytest.raises(ValueError,match='coverage'):
            validate_integration(altered,request,times,trains)
