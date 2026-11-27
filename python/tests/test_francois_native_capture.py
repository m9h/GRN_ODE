"""Integrity tests use recorded evidence and synthetic arrays, never integrations."""
import ast
from copy import deepcopy
import gzip
import hashlib
import inspect
import json
import logging
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from grn_memory import francois_native_capture as work
from grn_memory import copasi_output_capture as observer

@pytest.fixture(scope='module')
def ctx():
    return work.context()

def test_full_original_scope_and_every_control(ctx):
    plan,_,_,grid,_ = ctx
    assert len(plan['original_full_audit']['case_summaries']) == 118
    assert len(plan['selected_trials']) == 6
    assert len(plan['branches']) == 41
    assert len(plan['original_incomplete_branch_ids']) == 16
    assert len(grid) == 221001
    assert sum(len(t['record']['branches']) for t in plan['selected_trials']) == 48

@pytest.mark.parametrize('mutation',[
    lambda p:p.update(full_original_cases=117),
    lambda p:p.update(full_original_partitions=15),
    lambda p:p['original_full_audit']['case_summaries'].pop(next(iter(p['original_full_audit']['case_summaries']))),
    lambda p:p['selected_trials'].pop(),
    lambda p:p['branches'].pop(p['ordered_branch_ids'][-1]),
    lambda p:p['ordered_branch_ids'].reverse(),
    lambda p:p['original_incomplete_branch_ids'].pop(),
    lambda p:p.update(case_recovery_claimed=True),
    lambda p:p['acceptance'].update(rtol=2e-4),
    lambda p:p['branches'][p['ordered_branch_ids'][0]].update(sample_count=221000),
    lambda p:p['branches'][p['ordered_branch_ids'][0]]['occurrences'][0].update(artifact_id=1),
    lambda p:p['selected_trials'][0]['record'].update(responses=['invented']),
])
def test_scope_tampering_rejected(ctx,mutation):
    plan=deepcopy(ctx[0]);mutation(plan)
    with pytest.raises((ValueError,KeyError)):
        work.validate_scope(plan)

def test_repository_numerics_and_lock_are_identical_to_original(ctx):
    plan=ctx[0]
    assert len(plan['unchanged_repository_files_sha256']) > 20
    for name,expected in plan['unchanged_repository_files_sha256'].items():
        original=subprocess.check_output(['git','show',plan['base_revision']+':python/'+name],cwd=work.ROOT)
        assert hashlib.sha256(original).hexdigest() == expected == work.digest(work.ROOT/name)

def test_capture_observer_is_verbatim_previous_instrumentation():
    source=inspect.getsource(observer.observe_time_course).rstrip()
    assert hashlib.sha256(source.encode()).hexdigest() == 'f2908e3896e1845687907f34f704f60ffbca990c84ca0c98e11d872466183172'

def test_observer_forwards_exact_objects_and_restores_logger(tmp_path):
    logger=logging.getLogger('basico.task_timecourse')
    state=(logger.handlers,logger.level,logger.propagate)
    columns=['Time','x'];values=[0.,.1];sentinel=object()
    output=pd.DataFrame([[0.,1.],[.1,2.]],columns=columns)
    seen=[]
    def original(*args,**kwargs):
        seen.append((args,kwargs))
        logger.warning("MXSTEP reached: I1 = '100000'")
        return output
    monitor={}
    actual=observer.observe_time_course(original,tmp_path/'raw.npz',monitor,columns,model=sentinel,values=values,
        r_tol=1e-12,a_tol=1e-14,max_steps=100000,automatic=False,output_event=False,method='deterministic')
    assert actual is output
    assert seen[0][0][0] is columns and seen[0][1]['values'] is values and seen[0][1]['model'] is sentinel
    assert seen[0][1]['r_tol'] == 1e-12 and seen[0][1]['max_steps'] == 100000
    assert logger.handlers is state[0] and (logger.level,logger.propagate) == state[1:]
    assert monitor['shape'] == [2,2]
    with np.load(tmp_path/'raw.npz',allow_pickle=False) as raw:
        assert np.array_equal(raw['values'],output.to_numpy())
    assert 'MXSTEP' in gzip.decompress((tmp_path/'raw.log.gz').read_bytes()).decode()

def test_observer_preserves_exception_and_solver_log(tmp_path):
    logger=logging.getLogger('basico.task_timecourse');state=(logger.handlers,logger.level,logger.propagate)
    error=RuntimeError('native failure')
    def original(*args,**kwargs):
        logger.warning('solver stopped')
        raise error
    monitor={}
    with pytest.raises(RuntimeError) as caught:
        observer.observe_time_course(original,tmp_path/'raw.npz',monitor,values=[0.,1.])
    assert caught.value is error and 'raw_output' not in monitor
    assert 'solver stopped' in monitor['timecourse_log']['tail']
    assert logger.handlers is state[0] and (logger.level,logger.propagate)==state[1:]

@pytest.mark.parametrize('index',[-1,41,True,1.5])
def test_only_declared_integer_indices(ctx,index):
    with pytest.raises(ValueError):work.select(ctx[0],index)

def expected_runtime(ctx):
    return {'python':'3.12.13','system':'Linux','machine':'x86_64',
            'packages':deepcopy(next(iter(ctx[0]['source_reports'].values()))['report']['versions'])}

@pytest.mark.parametrize('field,value',[('python','3.13.0'),('system','Darwin'),('machine','aarch64')])
def test_runtime_drift_rejected(ctx,field,value):
    env=expected_runtime(ctx);env[field]=value
    with pytest.raises(ValueError):work.validate_runtime(env,ctx[0])

def test_package_drift_rejected(ctx):
    env=expected_runtime(ctx);env['packages']['python-copasi']='different'
    with pytest.raises(ValueError):work.validate_runtime(env,ctx[0])

@pytest.fixture
def saved_baseline(tmp_path,ctx):
    plan,path,info,times,_=ctx;bid,row=work.select(plan,0)
    (tmp_path/'protocol.xml').write_bytes(path.read_bytes())
    values=np.zeros((len(times),len(info['observables'])),dtype=np.float64)
    trace=pd.DataFrame(values,columns=info['observables']);trace.insert(0,'time',times)
    trajectories={};integrations={}
    for engine in ('roadrunner','copasi'):
        target=tmp_path/(engine+'.npz')
        np.savez_compressed(target,times=times,values=values,observables=np.asarray(info['observables']))
        trajectories[engine]={'file':target.name,'sha256':work.digest(target)}
        integrations[engine]={'request':row['specification']['integration_settings'][engine],
                              'completed':True,'status':'completed','samples':len(times)}
    raw=tmp_path/'copasi-raw.npz';columns=['Time']+info['observables']
    np.savez_compressed(raw,values=trace.to_numpy(),columns=np.asarray(columns))
    log=tmp_path/'copasi-raw.log.gz';log.write_bytes(gzip.compress(b'',mtime=0))
    request=integrations['copasi']['request']
    integrations['copasi'].update(raw_output={'file':raw.name,'sha256':work.digest(raw)},shape=list(trace.shape),columns=columns,
        settings={'r_tol':request['rtol'],'a_tol':request['atol'],'max_steps':100000,'automatic':False,'output_event':False,'method':'deterministic'},
        requested_samples=len(times),requested_times_sha256=hashlib.sha256(times.tobytes()).hexdigest(),
        timecourse_log={'file':log.name,'sha256':work.digest(log),'uncompressed_bytes':0,'tail':''})
    record={'status':'completed','plan_sha256':work.PLAN_SHA,'index':0,'record_id':bid,'specification':row['specification'],
        'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=work.ROOT,text=True).strip(),
        'implementation_sha256':work.source_hashes(),'model_sha256':info['sha256'],'samples':len(times),
        'observables':info['observables'],'times_sha256':hashlib.sha256(times.tobytes()).hexdigest(),'acceptance':work.ACCEPTANCE,
        'runtime':expected_runtime(ctx),'protocol_sha256':work.digest(tmp_path/'protocol.xml'),
        'integrations':integrations,'trajectories':trajectories,'comparison':work.comparison(trace,trace,**work.ACCEPTANCE),
        'case_recovery_claimed':False,'whole_model_pass_claimed':False}
    work.write(tmp_path/'execution.json',record)
    return tmp_path,record

def test_full_saved_arrays_are_independently_audited(saved_baseline,ctx):
    directory,_=saved_baseline;result=work.audit_result(directory,0,ctx)
    assert result['verified_complete_arrays']==2 and result['comparison']['passed']
    assert result['native_copasi']['returned_rows']==221001
    assert result['status']=='confirmed' and not result['case_recovery_claimed']

@pytest.mark.parametrize('mutation',[
    lambda r:r.update(source_revision='0'*40),
    lambda r:r.update(samples=221000),
    lambda r:r['integrations']['copasi']['settings'].update(max_steps=100001),
    lambda r:r['comparison'].update(max_scaled_error=0.5),
    lambda r:r['integrations']['copasi'].pop('raw_output'),
    lambda r:r['trajectories']['copasi'].update(file='../copasi.npz'),
    lambda r:r['integrations']['copasi']['timecourse_log'].update(tail='fabricated'),
])
def test_false_or_incomplete_saved_evidence_rejected(saved_baseline,ctx,mutation):
    directory,record=saved_baseline;mutation(record);work.write(directory/'execution.json',record)
    with pytest.raises((ValueError,KeyError)):work.audit_result(directory,0,ctx)

def test_array_shortening_rejected_even_with_updated_digest(saved_baseline,ctx):
    directory,record=saved_baseline;array=directory/'roadrunner.npz'
    with np.load(array,allow_pickle=False) as z:payload={k:z[k][:-1] if k!='observables' else z[k] for k in z.files}
    np.savez_compressed(array,**payload);record['trajectories']['roadrunner']['sha256']=work.digest(array)
    work.write(directory/'execution.json',record)
    with pytest.raises(ValueError):work.audit_result(directory,0,ctx)

def test_raw_capture_must_equal_accepted_values(saved_baseline,ctx):
    directory,record=saved_baseline;array=directory/'copasi-raw.npz'
    with np.load(array,allow_pickle=False) as z:values=z['values'].copy();columns=z['columns'].copy()
    values[100,1]=1.;np.savez_compressed(array,values=values,columns=columns)
    record['integrations']['copasi']['raw_output']['sha256']=work.digest(array)
    work.write(directory/'execution.json',record)
    with pytest.raises(ValueError,match='raw COPASI'):work.audit_result(directory,0,ctx)

@pytest.mark.parametrize('offset,accepted',[(5e-10,True),(2e-9,False)])
def test_original_native_clock_tolerance_is_preserved(saved_baseline,ctx,offset,accepted):
    directory,record=saved_baseline;array=directory/'roadrunner.npz'
    with np.load(array,allow_pickle=False) as z:payload={k:z[k].copy() for k in z.files}
    payload['times'][100]+=offset
    np.savez_compressed(array,**payload);record['trajectories']['roadrunner']['sha256']=work.digest(array)
    work.write(directory/'execution.json',record)
    if accepted:
        assert work.audit_result(directory,0,ctx)['comparison']['passed']
    else:
        with pytest.raises(AssertionError):work.audit_result(directory,0,ctx)

def test_original_six_unresolved_trials_cannot_disappear(ctx):
    rows=[]
    for bid,branch in ctx[0]['branches'].items():
        original=branch['occurrences'][0]['record'];windows=original.get('windows')
        rows.append({'record_id':bid,'windows':windows,'status':'confirmed' if original['passed'] else 'native_integration_failure',
                     'verified_complete_arrays':0})
    result=work.replay_trials(rows,ctx)
    assert result['unresolved_native_trials']==6 and len(result['selected_original_path_trials'])==6
    assert result['original_failed_cases_unchanged']==38 and not result['case_recovery_claimed']
    with pytest.raises(ValueError,match='forty controls'):work.replay_trials(rows[:-1],ctx)

def test_short_native_output_is_retained_as_a_failure(saved_baseline,ctx):
    directory,record=saved_baseline;raw=directory/'copasi-raw.npz'
    with np.load(raw,allow_pickle=False) as z:values=z['values'][:1000].copy();columns=z['columns'].copy()
    np.savez_compressed(raw,values=values,columns=columns)
    capture=record['integrations']['copasi']
    capture.update(completed=False,status='integration_error',error='ValueError: Unexpected output shape (1000, 7)',shape=list(values.shape))
    capture['raw_output']['sha256']=work.digest(raw)
    text="ERROR: MXSTEP reached: I1 = '100000'\n"
    log=directory/'copasi-raw.log.gz';log.write_bytes(gzip.compress(text.encode(),mtime=0))
    capture['timecourse_log'].update(sha256=work.digest(log),uncompressed_bytes=len(text.encode()),tail=text)
    record['trajectories'].pop('copasi');record['comparison']=None
    work.write(directory/'execution.json',record)
    result=work.audit_result(directory,0,ctx)
    assert result['status']=='native_integration_failure' and result['windows'] is None
    assert result['verified_complete_arrays']==1 and result['native_copasi']['returned_rows']==1000
    assert result['native_copasi']['step_limit_exhausted'] and not result['whole_model_pass_claimed']
