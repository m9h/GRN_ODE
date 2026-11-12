"""Synthetic full-grid fixtures test auditing, not scientific model outcomes."""

import json
import shutil
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import audit_scipy_breaking as auditor
from scripts import diagnose_scipy_breaking as producer


SOURCE=auditor.ROOT/'results/catalog-breaking-ciliberto28-shard0-refinement/source-evidence.json'


def write(path,value):
    path.write_text(json.dumps(value))


@pytest.fixture(scope='module')
def synthetic(tmp_path_factory):
    directory=tmp_path_factory.mktemp('synthetic-breaking-array-audit')
    source=json.loads(SOURCE.read_text());bid=source['failed_branches'][0]['record_id']
    _,_,info,grid,branches=producer.prepare(SOURCE,[bid]);original=branches[bid];spec=original['specification']
    settings=producer.requests(SimpleNamespace(reference_rtol=1e-13,reference_atol=1e-15,rtol=1e-10,atol=1e-12))
    sources=auditor.source_hashes();sources.update({n:auditor.digest(auditor.ROOT/n) for n in auditor.SOURCES})
    shutil.copyfile(SOURCE,directory/'source-evidence.json')
    report={'purpose':__doc__,'model_id':source['original_report']['biomodel_id'],'model_sha256':info['sha256'],
            'source_evidence_sha256':auditor.digest(SOURCE),'source_report_sha256':source['original_report_sha256'],
            'source_fingerprint':source['original_report']['fingerprint'],'requests':settings,
            'acceptance':{'rtol':2e-5,'atol':1e-7},'implementation_sha256':sources,
            'versions':{p:'synthetic-test-fixture' for p in auditor.PACKAGES},
            'sample_grid_sha256':auditor.hashlib.sha256(grid.tobytes()).hexdigest(),
            'selected_branch_ids':[bid],'case_recovery_claimed':False,
            'expected_branches':1,'status':'completed','confirmed_branches':1}
    report['fingerprint']=auditor.fingerprint({k:report[k] for k in auditor.META_KEYS})
    record={'fingerprint':report['fingerprint'],'record_id':bid,'specification':spec,
            'integrations':{},'traces':{},'status':'confirmed','case_recovery_claimed':False}
    trains=[auditor.ResetTrain(**t) for t in spec['reset_trains']]
    resets=sorted({float(v) for t in trains for v in t.times()});counts=[len(t.indices()) for t in trains]
    template=directory/'synthetic-template.npz'
    np.savez_compressed(template,times=grid,observables=np.asarray(info['observables']),
                        values=np.ones((len(grid),len(info['observables']))))
    for label,request in settings.items():
        path=directory/(bid+'-'+label+'.npz');shutil.copyfile(template,path)
        record['traces'][label]={'file':path.name,'sha256':auditor.digest(path)}
        outcome={'request':request,'completed':True,'sample_count':len(grid),'observables':info['observables']}
        if label.startswith('scipy'):
            outcome.update(backend='scipy.solve_ivp',rhs_backend='Jaxkineticmodel',jacobian='jax.jacfwd',
                           model_sha256=info['sha256'],method='Radau',rtol=request['rtol'],atol=request['atol'],
                           x64=True,absolute_time_preserved=True,expected_resets=len(resets),performed_resets=len(resets),
                           expected_train_reset_counts=counts,train_reset_counts=counts,
                           expected_segments=len(resets)+1,completed_segments=len(resets)+1,last_interval=[resets[-1],2210.])
        record['integrations'][label]=outcome
    record['comparisons']=checks(directory,record)
    record_path=directory/(bid+'.json');write(record_path,record)
    report['branches']=[{'record_id':bid,'file':record_path.name,'sha256':auditor.digest(record_path),'status':'confirmed'}]
    write(directory/'report.json',report)
    return directory


@pytest.fixture
def editable(synthetic,tmp_path):
    shutil.copytree(synthetic,tmp_path,dirs_exist_ok=True)
    return tmp_path


def checks(directory,record):
    first=next(iter(record['traces'].values()))
    with np.load(directory/first['file'],allow_pickle=False) as data:
        times=data['times'].copy();names=list(data['observables'])
    traces={k:auditor.trajectory(directory,record['record_id'],k,v,times,names) for k,v in record['traces'].items()}
    return {a+'_vs_'+b:auditor.comparison(traces[a],traces[b],rtol=2e-5,atol=1e-7)
            for i,a in enumerate(auditor.LABELS) for b in auditor.LABELS[i+1:] if a in traces and b in traces}


def change_record(directory,mutate,status=None):
    report=auditor.read(directory/'report.json');row=report['branches'][0];path=directory/row['file']
    record=auditor.read(path);mutate(record);write(path,record)
    row['sha256']=auditor.digest(path)
    if status:
        row['status']=status;report['confirmed_branches']=int(status=='confirmed')
    write(directory/'report.json',report)


def test_complete_selected_branch_does_not_claim_all_failures_or_cases(synthetic):
    result=auditor.audit(synthetic)
    assert result['selected_branch_count']==result['confirmed_branches']==1
    assert result['all_selected_branches_confirmed'] and not result['complete_captured_failure_coverage']
    assert not result['case_recovery_claimed'] and not result['full_model_coverage_claimed']
    branch=result['branches'][0]
    assert branch['samples']==221001 and branch['resets']==10500
    assert len(branch['comparisons'])==6 and set(branch['windows'])==set(auditor.LABELS)
    assert len(branch['windows']['scipy_refined'])==13


@pytest.mark.parametrize('field,value,message',[
    ('status','running','still running'),
    ('branches',[],'branch inventory'),
])
def test_incomplete_report_is_rejected(editable,field,value,message):
    report=auditor.read(editable/'report.json');report[field]=value;write(editable/'report.json',report)
    with pytest.raises(ValueError,match=message):auditor.audit(editable)


@pytest.mark.parametrize('field,value,message',[
    ('performed_resets',0,'Reset or segment'),
    ('absolute_time_preserved',False,'implementation or clock'),
    ('rtol',1e-6,'implementation or clock'),
])
def test_altered_integration_evidence_is_rejected(editable,field,value,message):
    change_record(editable,lambda r:r['integrations']['scipy_refined'].update({field:value}))
    with pytest.raises(ValueError,match=message):auditor.audit(editable)


def test_truncated_array_is_rejected_with_updated_digest(editable):
    def mutate(record):
        saved=record['traces']['scipy_refined'];path=editable/saved['file']
        with np.load(path,allow_pickle=False) as data:arrays={k:data[k].copy() for k in data.files}
        arrays['times']=arrays['times'][:-1];arrays['values']=arrays['values'][:-1]
        np.savez_compressed(path,**arrays);saved['sha256']=auditor.digest(path)
    change_record(editable,mutate)
    with pytest.raises(ValueError,match='observation inventory'):auditor.audit(editable)


def test_final_sample_is_checked_and_valid_mismatch_stays_failed(editable):
    def mutate(record):
        saved=record['traces']['scipy_refined'];path=editable/saved['file']
        with np.load(path,allow_pickle=False) as data:arrays={k:data[k].copy() for k in data.files}
        arrays['values'][-1,0]+=1.
        np.savez_compressed(path,**arrays);saved['sha256']=auditor.digest(path)
    change_record(editable,mutate)
    with pytest.raises(ValueError,match='pointwise comparisons'):auditor.audit(editable)
    def correct(record):
        record['comparisons']=checks(editable,record);record['status']='mismatch'
    change_record(editable,correct,status='mismatch')
    result=auditor.audit(editable)
    assert result['confirmed_branches']==0 and not result['all_selected_branches_confirmed']
    comparison=result['branches'][0]['comparisons']['roadrunner_vs_scipy_refined']
    assert not comparison['passed'] and comparison['worst_time']==2210.


def test_incomplete_engine_cannot_be_promoted(editable):
    def mutate(record):
        record['integrations']['scipy_refined'].update(completed=False,error='Explicit synthetic failure')
        record['traces'].pop('scipy_refined');record['comparisons']=checks(editable,record);record['status']='incomplete'
    change_record(editable,mutate,status='incomplete')
    result=auditor.audit(editable)
    assert result['confirmed_branches']==0 and result['branches'][0]['status']=='incomplete'


def test_case_recovery_claim_is_rejected_even_with_matching_fingerprint(editable):
    report=auditor.read(editable/'report.json');report['case_recovery_claimed']=True
    report['fingerprint']=auditor.fingerprint({k:report[k] for k in auditor.META_KEYS})
    write(editable/'report.json',report)
    with pytest.raises(ValueError,match='cannot claim case recovery'):auditor.audit(editable)
