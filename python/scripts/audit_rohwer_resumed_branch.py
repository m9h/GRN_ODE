"""Validate resume history, then use the unchanged original full-array checker.

Original evidence is never edited. A temporary view omits only the separately
validated attempt-history field and updates its record checksum in the report.
All numerical fields, source identities and array bytes remain unchanged. The
returned proof binds the actual files, checked history and temporary view hashes.
"""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import shutil
import tempfile

from scripts import collect_rohwer_later_controls as original
from scripts.run_rohwer_later_controls import digest,read,require,write


def bound_collector(run,batch):
    require(type(batch) is int and batch in (0,1),'Invalid original batch')
    spec=importlib.util.spec_from_file_location('_rohwer_continued_branch',Path(original.__file__))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.RUNS=deepcopy(original.RUNS)
    module.RUNS[batch]={k:run[k] for k in ('id','run_attempt','workflow_id','head_sha','path')}
    return module


def check_history(parent,current,directory):
    """Accept one unchanged or appended prior attempt per unfinished request."""
    history=current.get('previous_incomplete_attempts',{})
    require(type(history) is dict and set(history)<=set(original.LABELS)
            and all(type(v) is list and v for v in history.values()),'Invalid attempt-history inventory')
    if parent is None:
        require(not history,'A new branch cannot invent an earlier attempt')
        return {'prior_completed_requests':[],'appended_attempts':[]}
    for name in ('fingerprint','record_id','specification','case_recovery_claimed'):
        require(current[name]==parent[name],'Resume changed the original branch identity')
    previous=parent.get('previous_incomplete_attempts',{})
    require(type(previous) is dict and set(previous)<=set(original.LABELS)
            and all(type(v) is list and v for v in previous.values()),'Invalid parent history')
    preserved,appended=[],[]
    for label in original.LABELS:
        old_history,new_history=previous.get(label,[]),history.get(label,[])
        outcome=parent['integrations'].get(label)
        if outcome is None:
            require(new_history==old_history,'Unstarted request acquired invented history')
            continue
        if outcome['completed'] is True:
            require(current['integrations'].get(label)==outcome
                    and current['traces'].get(label)==parent['traces'][label]
                    and new_history==old_history,'Completed request metadata changed')
            saved=parent['traces'][label]
            path=directory/saved['file']
            require(saved['file']==parent['record_id']+'-'+label+'.npz'
                    and path.is_file() and not path.is_symlink() and digest(path)==saved['sha256'],
                    'Completed parent trajectory changed')
            preserved.append(label)
        elif new_history==old_history:
            require(current['integrations'].get(label)==outcome,'An unfinished attempt changed without history')
        else:
            require(new_history==old_history+[outcome],'Prior unsuccessful attempt was removed or changed')
            require(label in current['integrations'],'Appended history has no current request')
            appended.append(label)
    return {'prior_completed_requests':preserved,'appended_attempts':appended}


def audit(directory,row,entry,context,partition,run,*,parent_record=None,parent_record_sha256=None):
    directory=Path(directory)
    bid=row['record_id']
    module=bound_collector(run,partition['batch_index'])
    if entry is None or not directory.exists() or not (directory/'report.json').exists():
        # The unchanged collector keeps missing files and interrupted startup
        # explicit. No history is accepted without an actual saved record.
        return module.verify_branch(directory,row,entry,context,partition)
    allowed={'report.json','report.json.tmp','audit.json','audit.json.tmp',bid+'.json',bid+'.tmp'}
    allowed|={bid+'-'+label+'.npz' for label in original.LABELS}
    require(directory.is_dir() and not directory.is_symlink()
            and {p.name for p in directory.iterdir()}<=allowed
            and all(p.is_file() and not p.is_symlink() for p in directory.iterdir()),'Unexpected continuation branch files')
    before={p.name:digest(p) for p in directory.iterdir()}
    report=read(directory/'report.json')
    raw_record=directory/(bid+'.json')
    record=read(raw_record) if raw_record.exists() else None
    parent=None
    if parent_record is not None:
        require(parent_record_sha256 is not None and parent_record.is_file() and not parent_record.is_symlink()
                and digest(parent_record)==parent_record_sha256,'Parent checkpoint checksum differs')
        parent=read(parent_record)
    else:
        require(parent_record_sha256 is None,'Parent checksum has no checkpoint')
    if record is None:
        require(parent is None,'A preserved parent record disappeared')
        history_proof={'prior_completed_requests':[],'appended_attempts':[]}
    else:
        history_proof=check_history(parent,record,directory)
    if report['status']=='completed':
        require(record is not None and report['branch']['record_id']==bid
                and report['branch']['file']==bid+'.json'
                and report['branch']['sha256']==digest(raw_record),'Actual completed record checksum differs')
    normalized_record=deepcopy(record)
    if normalized_record is not None: normalized_record.pop('previous_incomplete_attempts',None)
    with tempfile.TemporaryDirectory(prefix='rohwer-resume-array-audit-') as tmp:
        view=Path(tmp)
        for path in directory.iterdir():
            if path.name in {'report.json','audit.json',bid+'.json'}: continue
            if path.suffix=='.npz':
                try: os.link(path,view/path.name)
                except OSError: shutil.copyfile(path,view/path.name)
            else: shutil.copyfile(path,view/path.name)
        if normalized_record is not None: write(view/(bid+'.json'),normalized_record)
        normalized_report=deepcopy(report)
        if report['status']=='completed': normalized_report['branch']['sha256']=digest(view/(bid+'.json'))
        write(view/'report.json',normalized_report)
        # Recompute through the existing interrupted-wrapper audit path, then
        # check this continuation wrapper's completion receipt against real files.
        audit_entry=deepcopy(entry)
        if audit_entry['status'] in ('confirmed','numerical_failure'): audit_entry['status']='time_limit'
        checked=module.verify_branch(view,row,audit_entry,context,partition)
        proof={'actual_report_sha256':before['report.json'],
               'actual_record_sha256':before.get(bid+'.json'),'parent_record_sha256':parent_record_sha256,
               'checked_report_sha256':digest(view/'report.json'),
               'checked_record_sha256':digest(view/(bid+'.json')) if normalized_record is not None else None,
               'metadata_projection':'previous_incomplete_attempts checked separately; report record checksum updated',
               'all_numerical_fields_and_array_bytes_unchanged':True,**history_proof}
    checked['producer_outcome']=entry
    if 'report_sha256' in checked: checked['report_sha256']=before['report.json']
    checked['resume_provenance']=proof
    receipt={'schema_version':1,'resume_provenance':proof,'array_audit':checked.get('independent_audit'),
             'comparisons':checked.get('comparisons'),'complete_diagnostic':checked['complete_diagnostic'],
             'verified_arrays':checked['verified_arrays'],'status':checked['status'],
             'audit_script_sha256':digest(Path(__file__)),'case_recovery_claimed':False}
    checked['continuation_audit']=receipt
    if (directory/'audit.json').exists():
        require(read(directory/'audit.json')==receipt,'Saved continuation audit does not reproduce')
    if entry['status'] in ('confirmed','numerical_failure'):
        require('audit.json' in before and checked['complete_diagnostic']
                and entry['status']==('confirmed' if checked['status']=='confirmed' else 'numerical_failure')
                and entry['report_sha256']==before['report.json']
                and entry['audit_sha256']==before['audit.json'],'Continuation completion receipt differs')
    require(before=={p.name:digest(p) for p in directory.iterdir()},'Original evidence changed during read-only audit')
    return checked
