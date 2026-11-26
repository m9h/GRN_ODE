"""Synthetic scheduling and preservation; never execute a numerical solver."""
from copy import deepcopy
from pathlib import Path
import subprocess

import pytest

from scripts import continue_rohwer_later as runner
from test_rohwer_later_controls import context, synthetic, save
from test_rohwer_later_collection import branch, partition_fixture, interrupt


def prepared(branch,context,tmp_path,*,partial=False):
    if partial: interrupt(branch,context)
    root,row,execution,validation,selection,runs,jobs=partition_fixture(branch,context,tmp_path)
    checked=runner.original.verify_partition(root,row,context,execution['wrapper_sha256'],validation)
    groups={
        'preserve_terminal_branch_ids':[b['record_id'] for b in checked['branches'] if b['complete_diagnostic']],
        'resume_partial_branch_ids':[b['record_id'] for b in checked['branches'] if b['status'] in runner.inputs.RESUMABLE],
        'unattempted_branch_ids':[b['record_id'] for b in checked['branches'] if b['status']=='not_started']}
    part={'index':row['index'],'batch_index':row['batch_index'],'parent_state':'eligible_for_continuation',
          'fixed_branch_ids':[b['record_id'] for b in row['branches']],
          'parent_run_id':row['run_id'],'parent_job_id':row['job_id'],'parent_artifact_id':123,
          'parent_archive_sha256':'sha256:'+'a'*64,'parent_execution_sha256':runner.digest(root/'execution.json'),
          'parent_evidence_sha256':{p.relative_to(root).as_posix():runner.digest(p) for p in root.rglob('*') if p.is_file()},
          'parent_verified_arrays':sum(b['verified_arrays'] for b in checked['branches']),**groups}
    parts=[None]*512;parts[row['index']]=part
    ctx={'plan':context[0],'scientific':context,'requirements':{'partitions':parts},'input_validation':validation}
    run={'id':50000000001,'run_attempt':1,'head_sha':'a'*40,'workflow_id':500000001,'path':runner.WORKFLOW}
    output=tmp_path/'continued'
    runner.initialize(root,output,row['index'],ctx,run)
    return ctx,run,part,output,root


@pytest.mark.parametrize('partial',[False,True])
def test_restore_preserves_every_parent_array_and_all_unattempted_branches(branch,context,tmp_path,partial):
    ctx,run,part,output,root=prepared(branch,context,tmp_path,partial=partial)
    result=runner.audit(output,part['index'],ctx,run=run)
    assert result['parent_arrays_preserved']==part['parent_verified_arrays']==(3 if partial else 4)
    assert len(result['branches'])==len(part['fixed_branch_ids'])
    assert not result['complete_selected_diagnostics']
    assert runner.read(output/'execution.json')['work_order']==part['unattempted_branch_ids']+part['resume_partial_branch_ids']
    assert runner.digest(root/'execution.json')==runner.digest(output/'lineage/execution.json')
    with pytest.raises(ValueError): runner.initialize(root,output,part['index'],ctx,run)


@pytest.mark.parametrize('change',['terminal_record','lineage','scope','order','false_completion','source','parent_array','request_metadata'])
def test_preserved_bytes_and_full_inventory_cannot_change(branch,context,tmp_path,change):
    partial=change in ('parent_array','request_metadata')
    ctx,run,part,output,_=prepared(branch,context,tmp_path,partial=partial)
    execution=runner.read(output/'execution.json')
    bid=branch[1]['record_id']
    if change=='terminal_record':
        path=output/bid/(bid+'.json');path.write_text(path.read_text()+' ')
    elif change=='lineage':
        path=output/'lineage/execution.json';path.write_text('{}')
    elif change=='scope': execution['branches'].pop()
    elif change=='order': execution['work_order'].reverse()
    elif change=='false_completion': execution['status']='completed'
    elif change=='source': execution['source_revision']='b'*40
    elif change=='parent_array':
        path=next((output/bid).glob('*.npz'))
        with path.open('ab') as stream:stream.write(b'changed')
    else:
        path=output/bid/(bid+'.json');record=runner.read(path)
        record['integrations']['roadrunner']['sample_count']-=1
        runner.write(path,record)
    runner.write(output/'execution.json',execution)
    with pytest.raises((ValueError,KeyError)):
        runner.audit(output,part['index'],ctx,run=run)


def test_timeout_saves_full_scope_without_restarting_completed_requests(branch,context,tmp_path,monkeypatch):
    ctx,run,part,output,_=prepared(branch,context,tmp_path,partial=True)
    calls=[];clock={'value':0.}
    monkeypatch.setattr(runner.time,'monotonic',lambda:clock['value'])
    def timeout(command,**kwargs):
        calls.append(command)
        clock['value']=11.
        raise subprocess.TimeoutExpired(command,kwargs['timeout'])
    monkeypatch.setattr(runner.subprocess,'run',timeout)
    result=runner.compute(output,part['index'],ctx,tmp_path/'inputs',10.)
    assert result==2 and len(calls)==1
    execution=runner.read(output/'execution.json')
    assert execution['attempted_now']==execution['work_order'][:1]
    assert execution['attempted_now'][0] in part['unattempted_branch_ids']
    assert execution['status']=='incomplete'
    checked=runner.audit(output,part['index'],ctx,run=run)
    assert checked['parent_arrays_preserved']==3 and not checked['complete_selected_diagnostics']
    assert len(checked['branches'])==len(part['fixed_branch_ids'])
    with pytest.raises(ValueError):runner.compute(output,part['index'],ctx,tmp_path/'inputs',10.)


def test_child_calls_original_kernel_with_original_metadata_and_resume(branch,context,tmp_path,monkeypatch):
    ctx,run,part,output,_=prepared(branch,context,tmp_path,partial=True)
    execution=runner.read(output/'execution.json')
    bid=execution['work_order'][0]
    execution['attempted_now']=[bid]
    execution['status']='running'
    next(e for e in execution['branches'] if e['record_id']==bid)['status']='running'
    runner.write(output/'execution.json',execution)
    calls=[]
    def kernel(*args,**kwargs):
        calls.append((args,kwargs))
        return {'record_id':bid,'file':bid+'.json','sha256':'synthetic-not-an-array','status':'confirmed'}
    monkeypatch.setattr(runner.producer,'compute_branch',kernel)
    runner.child(output,part['index'],bid,ctx)
    args,kwargs=calls[0]
    assert len(calls)==1 and kwargs=={'resume':True}
    assert args[0]==bid and args[1]==context[1]['branches'][bid]
    assert args[3]==runner.producer.metadata_for(context[0])
    assert args[4] is context[4] and args[5]==context[2] and args[6]==context[3]
    # A successful stub is not scientific completion: absent arrays/records fail
    # the real independent audit, even when the child report says completed.
    with pytest.raises((ValueError,FileNotFoundError)):
        runner.audit(output,part['index'],ctx,run=run)


@pytest.mark.parametrize('budget',[0,-1,float('nan'),float('inf'),19201,True])
def test_invalid_budget_cannot_launch_work(branch,context,tmp_path,budget):
    ctx,_,part,output,_=prepared(branch,context,tmp_path)
    with pytest.raises(ValueError):runner.compute(output,part['index'],ctx,tmp_path/'inputs',budget)
