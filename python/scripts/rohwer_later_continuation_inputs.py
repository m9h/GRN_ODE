"""Authenticate the complete Rohwer scope and the audited continuation parents.

The 512-partition inventory remains intact. Only the 231 available unfinished
partitions are eligible now; complete, pending and missing parents stay explicit.
"""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rohwer_missing_output as capture
from scripts import collect_rohwer_later_controls as original
from scripts.run_rohwer_later_controls import digest,read,require

BINDINGS=ROOT/'results/catalog-breaking-rohwer-later-continuation-20261126'
BINDING_SHA='a461e4b760b078d15560bc78575886fcf2ea800dfc93271043088852bd03dcef'
RESUMABLE={'interrupted','no_checkpoint','no_report'}


def check_bindings():
    require(digest(BINDINGS/'binding.json')==BINDING_SHA,'Fixed continuation binding differs')
    binding=read(BINDINGS/'binding.json')
    require(binding['schema_version']==binding['generation']==1
            and binding['frozen_plan_sha256']==original.PLAN_SHA
            and binding['original_capture_path']==str(capture.INPUTS.relative_to(ROOT))
            and binding['original_capture_sha256']==capture.CAPTURE_SHA,'Original scope binding differs')
    require(set(binding['files'])=={'requirements.json','parent-audit-summary.json'},'Binding inventory differs')
    for name,sha in binding['files'].items():
        require(not (BINDINGS/name).is_symlink() and digest(BINDINGS/name)==sha,'Pinned parent requirements changed')
    _,plan,selection=capture.check_capture()
    requirements=read(BINDINGS/'requirements.json')
    summary=read(BINDINGS/'parent-audit-summary.json')
    require(requirements['partition_count']==512 and requirements['fixed_branch_count']==10924
            and requirements['full_case_branch_count']==11674 and requirements['selected_case_count']==123
            and requirements['original_selection_sha256']==digest(capture.INPUTS/'original-selection.json')
            and requirements['original_capture_sha256']==capture.CAPTURE_SHA
            and requirements['source_collection_sha256']==summary['collection_sha256']
            and requirements['no_scope_reduction'] is True and requirements['case_recovery_claimed'] is False
            and requirements['full_model_coverage_claimed'] is False,'Complete scientific scope differs')
    parts=requirements['partitions']
    require([p['index'] for p in parts]==list(range(512)),'All 512 partitions required')
    snapshots=[{n:read(capture.INPUTS/f'original-api/batch-{b}/{n}.json') for n in ('run','jobs','artifacts')} for b in range(2)]
    classifications={k:[] for k in ('complete','eligible_for_continuation','missing_output','pending_original_job')}
    for part,row in zip(parts,selection['selected'],strict=True):
        index,batch=part['index'],part['batch_index']
        require(type(index) is int and type(batch) is int and batch==index//256==row['batch_index']
                and part['fixed_branch_ids']==[b['record_id'] for b in row['branches']], 'Full partition membership differs')
        state=part['parent_state']
        require(state in classifications,'Unknown parent state')
        classifications[state].append(index)
        snapshot=snapshots[batch]
        job=next(j for j in snapshot['jobs']['jobs'] if j['id']==row['job_id'])
        matches=[a for a in snapshot['artifacts']['artifacts'] if a['name']==row['artifact_name']]
        if state in ('missing_output','pending_original_job'):
            require(not matches and ((state=='missing_output' and index==23 and job['status']=='completed')
                    or (state=='pending_original_job' and job['status']!='completed')),'Unavailable parent classification differs')
            require(set(part)=={'index','batch_index','fixed_branch_ids','parent_state'},'Unavailable parent has invented outcomes')
            continue
        require(len(matches)==1,'Complete original artifact identity required')
        artifact=matches[0]
        original.validate_artifact(row,snapshot['run'],job,artifact)
        require(part['parent_run_id']==row['run_id'] and part['parent_job_id']==row['job_id']
                and part['parent_artifact_id']==artifact['id'] and part['parent_archive_sha256']==artifact['digest'],
                'Parent producer identity differs')
        groups=[part[k] for k in ('preserve_terminal_branch_ids','resume_partial_branch_ids','unattempted_branch_ids')]
        flat=sum(groups,[])
        require(len(flat)==len(set(flat))==len(part['fixed_branch_ids']) and set(flat)==set(part['fixed_branch_ids']),
                'A terminal failure or unfinished branch was omitted or duplicated')
        require((not groups[1] and not groups[2])==(state=='complete'),'Complete partition classification differs')
        require(part['parent_evidence_sha256']['execution.json']==part['parent_execution_sha256'], 'Parent execution hash differs')
    require(classifications['complete']==requirements['complete_indices']==[5]
            and classifications['eligible_for_continuation']==requirements['continue_indices']
            and len(requirements['continue_indices'])==231
            and classifications['missing_output']==requirements['missing_indices']==[23]
            and classifications['pending_original_job']==requirements['pending_indices']
            and len(requirements['pending_indices'])==279,'Every original partition state remains required')
    totals=[sum(len(p.get(k,[])) for p in parts) for k in
            ('preserve_terminal_branch_ids','resume_partial_branch_ids','unattempted_branch_ids')]
    require(totals==[requirements['terminal_diagnostics'],requirements['resumable_diagnostics'],
                     requirements['unstarted_diagnostics']]==[1432,231,3328]
            and sum(p.get('parent_verified_arrays',0) for p in parts)==requirements['parent_arrays']==6279,
            'Terminal outcomes, pending branches or parent arrays omitted')
    return {'binding':binding,'requirements':requirements,'plan':plan,'selection':selection,'snapshots':snapshots}


def selected_part(context,index,*,allow_complete=False):
    require(type(index) is int and 0<=index<512,'Invalid original partition index')
    part=context['requirements']['partitions'][index]
    allowed={'eligible_for_continuation'} | ({'complete'} if allow_complete else set())
    require(part['parent_state'] in allowed,'Only authenticated unfinished parents can be continued')
    return part


def verify_parent(archive,evidence,index,context,scientific_context,input_validation):
    part=selected_part(context,index,allow_complete=True)
    row=context['selection']['selected'][index]
    snapshot=context['snapshots'][row['batch_index']]
    artifact=next(a for a in snapshot['artifacts']['artifacts'] if a['id']==part['parent_artifact_id'])
    require(archive.is_file() and not archive.is_symlink() and archive.stat().st_size==artifact['size_in_bytes']
            and digest(archive)==artifact['digest'].removeprefix('sha256:'),'Original ZIP size or checksum differs')
    require(original.verify_zip(archive,evidence,extract=True)==part['parent_evidence_sha256'],
            'Original payload file inventory changed')
    runner_sha=context['plan']['runtime']['source_hashes']['scripts/run_rohwer_later_controls.py']
    checked=original.verify_partition(evidence,row,scientific_context,runner_sha,input_validation)
    require(checked['execution_sha256']==part['parent_execution_sha256'],'Parent execution differs')
    expected={
        'preserve_terminal_branch_ids':[b['record_id'] for b in checked['branches'] if b['complete_diagnostic']],
        'resume_partial_branch_ids':[b['record_id'] for b in checked['branches'] if not b['complete_diagnostic'] and b['status'] in RESUMABLE],
        'unattempted_branch_ids':[b['record_id'] for b in checked['branches'] if b['status']=='not_started']}
    require(all(part[k]==v for k,v in expected.items()),'Reaudited parent outcomes differ')
    require(sum(b['verified_arrays'] for b in checked['branches'])==part['parent_verified_arrays']
            and not checked['unverified_checkpoint_files'] and not any(b.get('unverified_arrays') for b in checked['branches']),
            'Parent arrays or checkpoint inventory differ')
    return checked


if __name__=='__main__':
    import json
    context=check_bindings()
    r=context['requirements']
    print(json.dumps({k:r[k] for k in ('partition_count','fixed_branch_count','full_case_branch_count',
                                      'selected_case_count','parent_arrays','terminal_diagnostics',
                                      'resumable_diagnostics','unstarted_diagnostics')}))
