"""Synthetic full-grid resume history; no numerical integrations."""
from copy import deepcopy

import pytest

from scripts import audit_rohwer_resumed_branch as resumed
from scripts import rohwer_later_continuation_inputs as inputs
from test_rohwer_later_controls import context, synthetic, save
from test_rohwer_later_collection import branch


def test_all_original_scope_and_terminal_failures_remain_declared():
    ctx=inputs.check_bindings()
    r=ctx['requirements']
    assert len(r['partitions'])==512 and len(r['continue_indices'])==231
    assert sum(len(p['fixed_branch_ids']) for p in r['partitions'])==10924
    assert r['full_case_branch_count']==11674 and r['selected_case_count']==123
    assert r['complete_indices']==[5] and r['partitions'][5]['terminal_status_counts']=={'confirmed':21,'mismatch':1}
    assert r['terminal_diagnostics']==1432 and r['parent_arrays']==6279
    assert r['resumable_diagnostics']==231 and r['unstarted_diagnostics']==3328
    assert r['missing_indices']==[23] and len(r['pending_indices'])==279


@pytest.mark.parametrize('index', [5,23,511,-1,512,True,23.0])
def test_complete_missing_pending_and_invalid_parents_cannot_be_dispatched(index):
    ctx=inputs.check_bindings()
    with pytest.raises(ValueError): inputs.selected_part(ctx,index)


@pytest.fixture
def continuation(branch,context,tmp_path):
    directory,row,entry=branch
    part=next(p for p in context[0]['partitions'] if row in p['branches'])
    run=deepcopy(resumed.original.RUNS[part['batch_index']])
    report=resumed.read(directory/'report.json')
    record=resumed.read(directory/(row['record_id']+'.json'))
    parent=deepcopy(record)
    label='scipy_refined'
    parent['integrations'][label]={'request':context[0]['requests'][label],'completed':False,
                                   'error':'Synthetic earlier failure, retained verbatim'}
    parent['traces'].pop(label)
    parent.update(status='running',comparisons={})
    parent_path=tmp_path/'parent-record.json'
    resumed.write(parent_path,parent)
    before=resumed.original.verify_branch(directory,row,entry,context,part)
    record['previous_incomplete_attempts']={label:[deepcopy(parent['integrations'][label])]}
    save(directory,report,record,context)
    return directory,row,entry,part,run,parent_path,before


def check(fixture,context):
    directory,row,entry,part,run,parent,_=fixture
    return resumed.audit(directory,row,entry,context,part,run,
                         parent_record=parent,parent_record_sha256=resumed.digest(parent))


def test_prior_failure_is_bound_and_original_array_math_reproduces(continuation,context):
    directory,row,entry,part,run,parent,before=continuation
    files={p.name:resumed.digest(p) for p in directory.iterdir()}
    result=check(continuation,context)
    assert result['complete_diagnostic'] and result['verified_arrays']==4
    assert result['independent_audit']==before['independent_audit']
    assert result['resume_provenance']['appended_attempts']==['scipy_refined']
    assert result['resume_provenance']['prior_completed_requests']==list(resumed.original.LABELS[:-1])
    assert result['resume_provenance']['actual_record_sha256']==resumed.digest(directory/(row['record_id']+'.json'))
    assert files=={p.name:resumed.digest(p) for p in directory.iterdir()}
    with pytest.raises(ValueError): resumed.original.verify_branch(directory,row,entry,context,part)
    assert resumed.original.RUNS[part['batch_index']]==run


def test_current_partial_request_stays_incomplete(continuation,context):
    directory,row,_,_,_,_,_=continuation
    report=resumed.read(directory/'report.json')
    record=resumed.read(directory/(row['record_id']+'.json'))
    record['traces'].pop('scipy_refined')
    (directory/(row['record_id']+'-scipy_refined.npz')).unlink()
    record['integrations']['scipy_refined']={'request':context[0]['requests']['scipy_refined'],'completed':False}
    record.update(status='running',comparisons={})
    save(directory,report,record,context)
    report.update(status='running',branch=None)
    resumed.write(directory/'report.json',report)
    result=check(continuation,context)
    assert not result['complete_diagnostic'] and result['verified_arrays']==3
    assert len(result['comparisons'])==3 and result['status']=='interrupted'


@pytest.mark.parametrize('change', ['removed_failure','changed_failure','duplicate_failure','invented_label',
    'completed_metadata','completed_trace','changed_source','bad_record_checksum','changed_request','false_completion'])
def test_history_source_and_actual_receipts_cannot_be_forged(continuation,context,change):
    directory,row,entry,_,_,_,_=continuation
    report=resumed.read(directory/'report.json')
    record=resumed.read(directory/(row['record_id']+'.json'))
    history=record['previous_incomplete_attempts']
    if change=='removed_failure': history.clear()
    elif change=='changed_failure': history['scipy_refined'][0]['error']='hidden'
    elif change=='duplicate_failure': history['scipy_refined']*=2
    elif change=='invented_label': history['invented']=[{}]
    elif change=='completed_metadata': record['integrations']['roadrunner']['sample_count']-=1
    elif change=='completed_trace': record['traces']['roadrunner']['sha256']='wrong'
    elif change=='changed_request': record['integrations']['scipy_refined']['request']={'rtol':1.0}
    elif change=='false_completion': entry.update(status='confirmed',report_sha256=resumed.digest(directory/'report.json'),audit_sha256=None)
    save(directory,report,record,context)
    if change=='changed_source': report['source_revision']='b'*40;resumed.write(directory/'report.json',report)
    if change=='bad_record_checksum': report['branch']['sha256']='wrong';resumed.write(directory/'report.json',report)
    with pytest.raises(ValueError): check(continuation,context)


def test_completed_wrapper_receipt_reproduces_without_checksum_cycle(continuation,context):
    directory,row,entry,_,_,_,_=continuation
    result=check(continuation,context)
    resumed.write(directory/'audit.json',result['continuation_audit'])
    entry.update(status='confirmed',report_sha256=resumed.digest(directory/'report.json'),
                 audit_sha256=resumed.digest(directory/'audit.json'))
    again=check(continuation,context)
    assert again['continuation_audit']==result['continuation_audit']
    assert again['complete_diagnostic']


def test_unbound_parent_and_invented_history_are_rejected(continuation,context):
    directory,row,entry,part,run,parent,_=continuation
    with pytest.raises(ValueError): resumed.audit(directory,row,entry,context,part,run)
    with pytest.raises(ValueError):
        resumed.audit(directory,row,entry,context,part,run,parent_record=parent,parent_record_sha256='wrong')
