"""Check source selection and resume guards without running the long diagnostic."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import diagnose_scipy_breaking as diagnostic


SOURCE=diagnostic.ROOT/'results/catalog-breaking-ciliberto28-shard0-refinement/source-evidence.json'


def test_original_ciliberto_failures_keep_all_observations():
    _,_,info,grid,branches=diagnostic.prepare(SOURCE)
    assert len(branches)==10 and len(info['observables'])==20
    assert len(grid)==221001 and grid[0]==0 and grid[-1]==2210.
    assert all(b['sample_count']==221001 and b['specification']['stop']==2210. for b in branches.values())
    counts=sorted(sum(len(diagnostic.ResetTrain(**t).indices()) for t in b['specification']['reset_trains'])
                  for b in branches.values())
    # Trained/untrained and cue/sham branches retain their distinct schedules.
    assert counts==[4995,4995,5994,5994,5994,9501,9501,10500,10500,10500]


@pytest.mark.parametrize('mutate,message',[
    (lambda e:e['failed_branches'][0].update(sample_count=220000),'observation inventory'),
    (lambda e:e['failed_branches'][0].update(passed=True),'Original branch identity'),
    (lambda e:e['failed_branches'].append(e['failed_branches'][0]),'Unique known'),
    (lambda e:e['original_report']['configuration'].update(comparison_atol=1e-3),'grid and acceptance'),
])
def test_changed_source_cannot_silently_change_protocol(tmp_path,mutate,message):
    source=json.loads(SOURCE.read_text());mutate(source)
    path=tmp_path/'source.json';path.write_text(json.dumps(source))
    with pytest.raises(ValueError,match=message):diagnostic.prepare(path)


def test_unknown_selected_branch_is_rejected():
    with pytest.raises(ValueError,match='Unique known'):
        diagnostic.prepare(SOURCE,['unknown'])


def test_refinement_preserves_tiny_absolute_tolerances():
    requests=diagnostic.requests(SimpleNamespace(reference_rtol=1e-13,reference_atol=1e-19,rtol=1e-10,atol=1e-20))
    assert requests['roadrunner_refined']=={'rtol':5e-14,'atol':5e-20}
    assert requests['scipy_refined']=={'method':'Radau','rtol':1e-11,'atol':1e-21}
    with pytest.raises(ValueError,match='Positive finite'):
        diagnostic.requests(SimpleNamespace(reference_rtol=0.,reference_atol=1e-19,rtol=1e-10,atol=1e-20))


def test_copasi_is_an_explicit_reference_with_its_own_versions():
    args=SimpleNamespace(reference_engine='copasi',reference_rtol=1e-13,reference_atol=1e-19,
                         rtol=1e-11,atol=1e-13)
    settings=diagnostic.requests(args)
    assert list(settings)==['copasi','copasi_refined','scipy','scipy_refined']
    assert settings['copasi_refined']=={'rtol':5e-14,'atol':5e-20}
    assert {'python-copasi','copasi-basico'}<=diagnostic.native_packages('copasi')
    args.reference_engine='unknown'
    with pytest.raises(ValueError,match='native reference'):diagnostic.requests(args)


@pytest.mark.parametrize('engine',['roadrunner','copasi'])
def test_native_choice_reaches_adapter_and_cannot_change_on_resume(tmp_path,monkeypatch,engine):
    # Synthetic tiny fixture tests dispatch and cache identity, not model outcomes.
    import pandas as pd
    evidence=tmp_path/'source.json';evidence.write_text('{}')
    output=tmp_path/'output';output.mkdir()
    times=np.array([0.,1.]);names=['synthetic'];bid='synthetic-branch'
    spec={'stop':1.,'reset_trains':[],
          'integration_settings':{e:{'rtol':1e-12,'atol':1e-14} for e in ('roadrunner','copasi')}}
    original={'biomodel_id':'synthetic','fingerprint':'synthetic-original'}
    monkeypatch.setattr(diagnostic,'prepare',lambda *a:({'original_report':original,'original_report_sha256':'test'},
                        tmp_path/'model.xml',{'sha256':'test','observables':names},times,{bid:{'specification':spec}}))
    monkeypatch.setattr(diagnostic,'source_hashes',lambda:{})
    monkeypatch.setattr(diagnostic,'version',lambda name:'synthetic-test-fixture')
    calls=[]
    def native(path,times,trains,chosen,**settings):
        calls.append(chosen);return pd.DataFrame({'time':times,'synthetic':[1.,1.]})
    monkeypatch.setattr(diagnostic,'protocol_trajectory',native)
    def stopped(*a,**kw):raise RuntimeError('Synthetic Radau failure; no model integration performed')
    monkeypatch.setattr(diagnostic,'scipy_protocol_trajectory',stopped)
    args=SimpleNamespace(evidence=evidence,output=output,branch=[],resume=False,reference_engine=engine,
                         reference_rtol=1e-13,reference_atol=1e-15,rtol=1e-11,atol=1e-13)
    diagnostic.diagnose(args)
    assert calls==[engine,engine]
    report=json.loads((output/'report.json').read_text())
    assert report['reference_engine']==engine and report['confirmed_branches']==0
    args.resume=True;args.reference_engine='copasi' if engine=='roadrunner' else 'roadrunner'
    with pytest.raises(ValueError,match='Resume requires unchanged'):diagnostic.diagnose(args)
    assert calls==[engine,engine]


@pytest.fixture
def saved(tmp_path):
    # Explicitly synthetic miniature array: this only tests resume validation.
    times=np.array([0.,2.5,3.]);names=['synthetic']
    path=tmp_path/'synthetic.npz'
    np.savez_compressed(path,times=times,observables=np.asarray(names),values=np.ones((3,1)))
    trains=[diagnostic.ResetTrain(1.,2.,{'synthetic':1.})]
    resets=list(trains[0].times());count=len(resets)
    request={'method':'Radau','rtol':1e-10,'atol':1e-12}
    evidence={'completed':True,'request':request,'sample_count':3,'observables':names,
              'model_sha256':'synthetic','method':'Radau','rtol':1e-10,'atol':1e-12,
              'x64':True,'absolute_time_preserved':True,'expected_resets':count,'performed_resets':count,
              'expected_train_reset_counts':[count],'train_reset_counts':[count],
              'expected_segments':count+1,'completed_segments':count+1,'last_interval':[resets[-1],3.]}
    return {'path':path,'saved':{'file':path.name,'sha256':diagnostic.digest(path)},'times':times,'names':names,
            'evidence':evidence,'label':'scipy','request':request,'trains':trains,'model_sha':'synthetic'}


def test_complete_synthetic_cache_is_read_without_integration(saved):
    trace=diagnostic.load_saved(**saved)
    assert len(trace)==3 and list(trace.columns)==['time','synthetic']


@pytest.mark.parametrize('field,value', [('performed_resets',0),('absolute_time_preserved',False),('x64',False)])
def test_incomplete_reset_or_precision_evidence_cannot_resume(saved,field,value):
    saved['evidence'][field]=value
    with pytest.raises(ValueError,match='reset, precision and clock'):
        diagnostic.load_saved(**saved)


def test_truncated_cached_array_is_rejected_with_updated_checksum(saved):
    path=saved['path']
    np.savez_compressed(path,times=saved['times'][:-1],values=np.ones((2,1)),observables=np.asarray(saved['names']))
    saved['saved']['sha256']=diagnostic.digest(path)
    with pytest.raises(ValueError,match='Complete original trajectory'):
        diagnostic.load_saved(**saved)
