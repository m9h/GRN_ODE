"""Bounded submissions, full-scope routing and immutable parent evidence.

API and numerical arrays below are synthetic. The released input/runtime check
and the separate real-parent restoration exercise authenticate actual evidence.
No numerical integration is performed in these tests.
"""
from copy import deepcopy
from pathlib import Path
import shutil
import zipfile

import pytest

from scripts import collect_rohwer_later_continuation as collection
from scripts import audit_rohwer_full_cases as full
from test_rohwer_later_controls import context, synthetic
from test_rohwer_later_collection import branch
from test_rohwer_full_case_audit import first_plan, stage_fixture
from test_continue_rohwer_later import prepared

runner=collection.runner
read,write=runner.read,runner.write


@pytest.fixture(scope='module')
def captured():
    return runner.inputs.check_bindings()


@pytest.fixture
def api(monkeypatch,captured):
    monkeypatch.setattr(runner.inputs,'check_bindings',lambda:deepcopy(captured))
    revision='a'*40
    proof={'revision':revision,'synthetic_test_fixture':True,
           'continuation_files':{name:runner.digest(runner.ROOT/name) for name in collection.SOURCE_FILES}}
    monkeypatch.setattr(collection,'source_proof',lambda selected:deepcopy(proof))
    return make_api([0,1,2,44],revision)


def make_api(indices,revision='a'*40,run_id=50000000001):
    run={'id':run_id,'run_attempt':1,'workflow_id':500000001,'head_sha':revision,
         'path':runner.WORKFLOW,'event':'workflow_dispatch','repository':{'full_name':'m9h/GRN_ODE'}}
    gate={'id':run_id*3,'name':'validation','run_id':run_id,'run_attempt':1,'head_sha':revision,
          'status':'completed','conclusion':'success'}
    jobs=[gate]+[{**gate,'id':gate['id']+n+1,'name':f'rohwer-later-continuation-{i}',
                  'status':'queued','conclusion':None} for n,i in enumerate(indices)]
    return run,{'total_count':len(jobs),'jobs':jobs},revision,indices


def descriptor(tmp_path,api,artifacts=None):
    run,jobs,revision,indices=api
    root=tmp_path/str(run['id']);(root/'api').mkdir(parents=True)
    write(root/'binding.json',collection.bind(*api))
    for name,data in [('run',run),('jobs',jobs),('artifacts',artifacts or {'total_count':0,'artifacts':[]})]:
        write(root/'api'/(name+'.json'),data)
    write(root/'descriptor.json',{'binding':'binding.json','snapshots':'api','cache':'cache'})
    return root/'descriptor.json'


def test_bounded_batch_keeps_all_231_requirements_and_512_original_partitions(api,captured):
    binding=collection.bind(*api)
    assert binding['requested_indices']==[0,1,2,44]
    assert len(binding['required_continuation_indices'])==231
    assert len(binding['eligible_indices_not_in_this_run'])==227
    assert len(binding['selected'])==512
    assert sum(len(row['branches']) for row in binding['selected'])==10924
    assert binding['required_full_branches']==11674 and binding['required_cases']==123
    original=captured['selection']['selected']
    assert sum(a==b for a,b in zip(binding['selected'],original,strict=True))==508
    assert all(binding['selected'][i]['previous']==original[i] for i in binding['requested_indices'])
    assert binding['selected'][5]==original[5] and binding['selected'][23]==original[23]
    assert not binding['case_recovery_claimed'] and not binding['full_model_coverage_claimed']


@pytest.mark.parametrize('value',['[]','[0,1,2,3,4]','[5]','[23]','[511]','[0,0]',
                                 '[1,0]','[true]','[0.0]','null','{}','[-1]'])
def test_only_bounded_unique_eligible_indices_can_be_requested(captured,value):
    with pytest.raises(ValueError): collection.selected_indices(value,captured)


@pytest.mark.parametrize('change',['gate_queued','gate_failed','missing_job','extra_job','duplicate_id',
                                 'wrong_name','wrong_source','wrong_attempt','wrong_workflow','wrong_repo','wrong_run'])
def test_actual_jobs_and_successful_gate_must_match_exactly(api,change):
    run,jobs,revision,indices=api
    if change=='gate_queued': jobs['jobs'][0]['status']='queued'
    elif change=='gate_failed': jobs['jobs'][0]['conclusion']='failure'
    elif change=='missing_job': jobs['jobs'].pop()
    elif change=='extra_job': jobs['jobs'].append(deepcopy(jobs['jobs'][-1]));jobs['total_count']+=1
    elif change=='duplicate_id': jobs['jobs'][1]['id']=jobs['jobs'][0]['id']
    elif change=='wrong_name': jobs['jobs'][1]['name']='rohwer-later-continuation-5'
    elif change=='wrong_source': jobs['jobs'][1]['head_sha']='b'*40
    elif change=='wrong_attempt': jobs['jobs'][1]['run_attempt']=2
    elif change=='wrong_workflow': run['path']='wrong.yml'
    elif change=='wrong_repo': run['repository']['full_name']='different/repo'
    else: jobs['jobs'][1]['run_id']+=1
    with pytest.raises(ValueError): collection.bind(*api)


@pytest.mark.parametrize('change',['selection','branch','required_scope','eligible_remainder','gate','artifact_pages'])
def test_persisted_binding_cannot_narrow_or_change(api,tmp_path,change):
    path=descriptor(tmp_path,api);binding=read(path.parent/'binding.json')
    if change=='selection': binding['selected'].pop()
    elif change=='branch': binding['selected'][0]['branches'].pop()
    elif change=='required_scope': binding['required_continuation_indices'].pop()
    elif change=='eligible_remainder': binding['eligible_indices_not_in_this_run'].pop()
    elif change=='gate': binding['validation_job_id']+=1
    else: write(path.parent/'api/artifacts.json',{'total_count':1,'artifacts':[]})
    write(path.parent/'binding.json',binding)
    with pytest.raises(ValueError): collection.Continuation(path)


def uploaded(api,index=0):
    run,jobs,_,indices=api
    job=jobs['jobs'][indices.index(index)+1]
    job.update(status='completed',conclusion='failure',started_at='2026-11-26T00:00:00Z',completed_at='2026-11-26T06:00:00Z')
    artifact={'id':900001,'name':f'rohwer-controls-continuation-partition-{index}-attempt-1',
              'expired':False,'workflow_run':{'id':run['id'],'head_sha':run['head_sha']},
              'created_at':'2026-11-26T05:59:00Z','digest':'sha256:'+'c'*64,'size_in_bytes':100}
    return job,artifact


@pytest.mark.parametrize('change',['expired','source','run','name','checksum','size','before_job','after_job','attempt'])
def test_artifact_identity_and_timing_cannot_change(api,tmp_path,change):
    job,artifact=uploaded(api)
    path=descriptor(tmp_path,api)
    selected=collection.Continuation(path);row=selected.binding['selected'][0]
    if change=='expired': artifact['expired']=True
    elif change=='source': artifact['workflow_run']['head_sha']='b'*40
    elif change=='run': artifact['workflow_run']['id']+=1
    elif change=='name': artifact['name']='different'
    elif change=='checksum': artifact['digest']='sha256:wrong'
    elif change=='size': artifact['size_in_bytes']=0
    elif change=='before_job': artifact['created_at']='2026-11-25T23:59:00Z'
    elif change=='after_job': artifact['created_at']='2026-11-26T06:01:00Z'
    else: job['run_attempt']=2
    with pytest.raises(ValueError):selected.validate_artifact(row,api[0],job,artifact)


def test_disjoint_batches_combine_without_losing_unsubmitted_work(api,tmp_path):
    first=descriptor(tmp_path,api)
    second=descriptor(tmp_path,make_api([4,6],run_id=50000000002))
    combined=collection.ContinuationSet([first,second])
    assert combined.indices=={0,1,2,4,6,44}
    assert combined.for_index(4).run['id']==50000000002
    assert combined.for_index(5) is None
    output=tmp_path/'out';output.mkdir()
    result=combined.preserve(output)
    assert len(result['required_continuation_indices'])==231
    assert len(result['eligible_indices_not_submitted'])==225
    assert result['required_full_branches']==11674 and len(result['batches'])==2
    with pytest.raises(ValueError,match='Conflicting'):collection.ContinuationSet([first,first])


def align_original_api(paths,captured):
    selection=captured['selection']
    write(paths['selection'],selection)
    for b in range(2):
        jobs=read(runner.inputs.capture.INPUTS/f'original-api/batch-{b}/jobs.json')
        artifacts=read(paths['snapshots']/f'batch-{b}/artifacts.json')['artifacts']
        for job in jobs['jobs']:
            if job['name']=='validation': continue
            row=next(r for r in selection['selected'] if r['job_id']==job['id'])
            if any(a['name']==row['artifact_name'] for a in artifacts):
                job.update(status='completed',conclusion='timed_out',started_at='2026-11-18T23:00:00Z',completed_at='2026-11-19T05:00:00Z')
            else: job.update(status='queued',conclusion=None)
        write(paths['snapshots']/f'batch-{b}/jobs.json',jobs)


@pytest.mark.parametrize('state',['queued','running_with_artifact','terminal_no_artifact','duplicate_artifact'])
def test_pending_children_keep_original_audited_arrays_and_full_scope(api,captured,branch,context,first_plan,tmp_path,state):
    paths,validation,output,store,_=stage_fixture(branch,context,tmp_path)
    align_original_api(paths,captured)
    index=next(p['index'] for p in context[0]['partitions'] if branch[1] in p['branches'])
    assert index in captured['requirements']['continue_indices']
    selected_api=make_api([index])
    artifacts=[]
    if state!='queued':
        job,artifact=uploaded(selected_api,index)
        if state=='running_with_artifact':job.update(status='in_progress',conclusion=None);artifacts=[artifact]
        elif state=='duplicate_artifact':artifacts=[artifact,{**artifact,'id':900002}]
    path=descriptor(tmp_path,selected_api,{'total_count':len(artifacts),'artifacts':artifacts})
    selected=collection.Continuation(path)
    if state=='duplicate_artifact':
        with pytest.raises(ValueError,match='Duplicate continuation'):selected.available(index)
        return
    result=full.verify_stage('controls',paths,context,first_plan,validation,output,store,continuation=selected)
    assert not result['verification_errors'] and len(store)==11674
    assert store[branch[1]['record_id']]['verified_arrays']==4
    assert sum(r['complete_diagnostic'] for r in store.index.values())==1
    assert result['controls_continuation']['original_parents_retained_while_waiting']==[index]
    assert result['controls_continuation']['available_replacement_indices']==[]


@pytest.mark.parametrize('change',[None,'zip','preserved_array'])
def test_uploaded_continuation_reaudits_real_array_format_and_rejects_tampering(
        api,captured,branch,context,first_plan,tmp_path,monkeypatch,change):
    paths,validation,output,store,_=stage_fixture(branch,context,tmp_path)
    align_original_api(paths,captured)
    prep=tmp_path/'prep';prep.mkdir()
    ctx,run,part,continued,_=prepared(branch,context,prep)
    index=part['index'];assert index in captured['requirements']['continue_indices']
    selected_api=make_api([index]);job,artifact=uploaded(selected_api,index)
    # Explicit synthetic parent evidence replaces only this fixture's requirement
    # payload; the fixed branch inventory and all 512 original jobs remain intact.
    fixture=deepcopy(captured);fixture['plan']=context[0]
    fixture['requirements']['partitions'][index]=part
    monkeypatch.setattr(runner.inputs,'check_bindings',lambda:deepcopy(fixture))
    original_show=runner.subprocess.check_output
    def source_bytes(command,**kwargs):
        if command[:2]==['git','show'] and command[2].startswith('a'*40+':python/'):
            return (runner.ROOT/command[2].split(':python/',1)[1]).read_bytes()
        return original_show(command,**kwargs)
    monkeypatch.setattr(runner.subprocess,'check_output',source_bytes)
    path=descriptor(tmp_path,selected_api)
    destination=path.parent/'cache'/str(run['id'])/'attempt-1'/f'artifact-{artifact["id"]}'
    destination.mkdir(parents=True);shutil.copytree(continued,destination/'evidence')
    if change=='preserved_array':
        target=next((destination/'evidence'/branch[1]['record_id']).glob('*.npz'))
        with target.open('ab') as stream:stream.write(b'tampered')
    archive=destination/'download.zip'
    with zipfile.ZipFile(archive,'w') as stream:
        for file in (destination/'evidence').rglob('*'):
            if file.is_file():stream.write(file,file.relative_to(destination/'evidence'))
    artifact.update(digest='sha256:'+runner.digest(archive),size_in_bytes=archive.stat().st_size)
    write(path.parent/'api/artifacts.json',{'total_count':1,'artifacts':[artifact]})
    if change=='zip':
        with archive.open('ab') as stream:stream.write(b'tampered')
    selected=collection.Continuation(path)
    result=full.verify_stage('controls',paths,context,first_plan,validation,output,store,continuation=selected)
    assert len(store)==11674
    assert bool(result['verification_errors'])==(change is not None)
    assert result['controls_continuation']['available_replacement_indices']==[index]
    if change is None:
        assert store[branch[1]['record_id']]['verified_arrays']==4
        assert store[branch[1]['record_id']]['run_id']==run['id']
        assert result['partitions'][0]['continuation_run']['id']==run['id']
    else:
        # A corrupt replacement fails visibly; it must never silently fall back
        # to its valid original parent and conceal the new evidence failure.
        assert not any(r['complete_diagnostic'] for r in store.index.values())
