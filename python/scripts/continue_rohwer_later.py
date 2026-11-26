"""Continue unfinished Rohwer controls with the frozen numerical implementation.

Terminal diagnostics are immutable. Finished requests in partial branches are
reused byte for byte; earlier unsuccessful attempts remain in checked history.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rohwer_later_continuation_inputs as inputs
from scripts import audit_rohwer_resumed_branch as resumed
from scripts import run_rohwer_later_controls as producer
from scripts.run_rohwer_later_controls import digest,read,require,write

original=inputs.original
SCRIPT='scripts/continue_rohwer_later.py'
WORKFLOW='.github/workflows/rohwer-later-continuation.yml'


def context_for(bundle):
    context=inputs.check_bindings()
    context['scientific']=producer.load_plan(inputs.capture.PLAN,original.PLAN_SHA,bundle)
    context['input_validation']=producer.inputs.validate(bundle,producer.MANIFEST_SHA)
    return context


def lineage_files(part):
    partial=set(part['resume_partial_branch_ids'])
    return {name:sha for name,sha in part['parent_evidence_sha256'].items()
            if name=='execution.json' or (name.split('/')[0] in partial and not name.endswith('.npz'))}


def preservation(output,part):
    lineage=output/'lineage'
    files=lineage_files(part)
    actual={p.relative_to(lineage).as_posix():digest(p) for p in lineage.rglob('*') if p.is_file()}
    require(actual==files and all(not p.is_symlink() for p in lineage.rglob('*')),'Original lineage metadata changed')
    terminal=set(part['preserve_terminal_branch_ids'])
    arrays=0
    for name,sha in part['parent_evidence_sha256'].items():
        if name.endswith('.npz') or name.split('/')[0] in terminal or name=='input-validation.json':
            path=output/name
            require(path.is_file() and not path.is_symlink() and digest(path)==sha,'Preserved parent bytes changed: '+name)
            arrays+=int(name.endswith('.npz'))
    for bid in part['resume_partial_branch_ids']:
        parent_path=lineage/bid/(bid+'.json')
        if parent_path.exists():
            current=output/bid/(bid+'.json')
            require(current.is_file() and not current.is_symlink(),'Parent record disappeared')
            resumed.check_history(read(parent_path),read(current),output/bid)
    require(arrays==part['parent_verified_arrays'],'A parent trajectory was omitted')
    return arrays


def initialize(evidence,output,index,context,identity):
    part=inputs.selected_part(context,index)
    require(not output.exists(),'Use a new continuation directory')
    shutil.copytree(evidence,output)
    for name,sha in lineage_files(part).items():
        source=output/name
        require(digest(source)==sha,'Parent metadata changed before continuation')
        target=output/'lineage'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
    parent=read(output/'lineage/execution.json')
    entries={b['record_id']:b for b in parent['branches']}
    rows=context['plan']['partitions'][index]['branches']
    execution={'schema_version':1,'generation':1,'binding_sha256':inputs.BINDING_SHA,
        'model_id':context['plan']['model_id'],'plan_sha256':original.PLAN_SHA,
        'partition_index':index,'batch_index':part['batch_index'],'selected_branches':rows,
        'runtime':context['plan']['runtime'],'parent_run_id':part['parent_run_id'],
        'parent_job_id':part['parent_job_id'],'parent_artifact_id':part['parent_artifact_id'],
        'parent_archive_sha256':part['parent_archive_sha256'],
        'source_revision':identity['head_sha'],'run_id':str(identity['id']),
        'run_attempt':str(identity['run_attempt']),'workflow_path':WORKFLOW,
        'runner_sha256':digest(Path(__file__)),'audit_script_sha256':digest(Path(resumed.__file__)),
        'preserved_terminal_ids':part['preserve_terminal_branch_ids'],
        'work_order':part['unattempted_branch_ids']+part['resume_partial_branch_ids'],
        'attempted_now':[],'branches':[entries.get(b['record_id'],{**b,'status':'not_started'}) for b in rows],
        'status':'prepared','case_recovery_claimed':False,'full_model_coverage_claimed':False,
        'started_at':datetime.now(timezone.utc).isoformat()}
    execution['parent_arrays_preserved']=preservation(output,part)
    write(output/'execution.json',execution)
    return execution


def identity_for(execution):
    return {'id':int(execution['run_id']),'run_attempt':int(execution['run_attempt']),
            'head_sha':execution['source_revision'],'workflow_id':0,'path':WORKFLOW}


def unchanged_parent_branch(directory,bid,part):
    expected={name.split('/',1)[1]:sha for name,sha in part['parent_evidence_sha256'].items() if name.startswith(bid+'/')}
    if not directory.exists(): return not expected
    require(directory.is_dir() and not directory.is_symlink(),'Unsafe branch directory')
    actual={p.name:digest(p) for p in directory.iterdir() if p.is_file() and not p.is_symlink()}
    return actual==expected and all(p.is_file() and not p.is_symlink() for p in directory.iterdir())


def audit(output,index,context,*,run=None,revision=None):
    part=inputs.selected_part(context,index)
    rows=context['plan']['partitions'][index]['branches']
    execution=read(output/'execution.json')
    require(read(output/'input-validation.json')==context['input_validation'],'Authenticated input validation differs')
    require(execution['schema_version']==execution['generation']==1 and execution['binding_sha256']==inputs.BINDING_SHA
            and execution['model_id']==context['plan']['model_id'] and execution['plan_sha256']==original.PLAN_SHA
            and execution['partition_index']==index and execution['batch_index']==part['batch_index']
            and execution['selected_branches']==rows and execution['runtime']==context['plan']['runtime']
            and execution['case_recovery_claimed'] is False and execution['full_model_coverage_claimed'] is False,
            'Continuation scope or runtime changed')
    require(all(execution[k]==part[k] for k in ('parent_run_id','parent_job_id','parent_artifact_id','parent_archive_sha256')),
            'Original parent identity changed')
    for key,name in [('runner_sha256',SCRIPT),('audit_script_sha256','scripts/audit_rohwer_resumed_branch.py')]:
        expected=(hashlib.sha256(subprocess.check_output(['git','show',revision+':python/'+name],cwd=ROOT)).hexdigest()
                  if revision is not None else digest(ROOT/name))
        require(execution[key]==expected,'Continuation implementation source differs')
    identity=identity_for(execution)
    require(identity['id']>0 and identity['run_attempt']==1 and execution['workflow_path']==WORKFLOW,
            'Explicit first-attempt continuation identity required')
    if run is not None:
        require(all(identity[k]==run[k] for k in ('id','run_attempt','head_sha','path')),'Selected continuation run differs')
        identity=run
    if revision is not None: require(identity['head_sha']==revision,'Selected source revision differs')
    order=part['unattempted_branch_ids']+part['resume_partial_branch_ids']
    attempted=execution['attempted_now']
    require(execution['preserved_terminal_ids']==part['preserve_terminal_branch_ids'] and execution['work_order']==order
            and attempted==order[:len(attempted)],'Terminal outcome or continuation scheduling changed')
    entries=execution['branches']
    require([{k:e[k] for k in ('record_id','sample_count','origin')} for e in entries]==rows,'Original partition membership changed')
    parent={e['record_id']:e for e in read(output/'lineage/execution.json')['branches']}
    checked=[]
    for row,entry in zip(rows,entries,strict=True):
        bid=row['record_id'];directory=output/bid
        require(entry['status'] in {'not_started','running','confirmed','numerical_failure','time_limit','execution_or_audit_failure'},
                'Unknown continuation outcome')
        original_entry=parent.get(bid)
        if bid not in attempted:
            require(entry==parent.get(bid,{**row,'status':'not_started'}) and unchanged_parent_branch(directory,bid,part),
                    'Unattempted parent outcome changed')
            result=original.verify_branch(directory,row,original_entry,context['scientific'],context['plan']['partitions'][index])
        elif original_entry is not None and unchanged_parent_branch(directory,bid,part):
            require(entry['status'] not in ('confirmed','numerical_failure'),'Unchanged partial parent falsely claimed complete')
            result=original.verify_branch(directory,row,original_entry,context['scientific'],context['plan']['partitions'][index])
            result['current_attempt_started_no_new_evidence']=True
        else:
            old=output/'lineage'/bid/(bid+'.json')
            result=resumed.audit(directory,row,entry,context['scientific'],context['plan']['partitions'][index],identity,
                parent_record=old if old.exists() else None,parent_record_sha256=digest(old) if old.exists() else None)
        checked.append(result)
    arrays=preservation(output,part)
    require(execution['parent_arrays_preserved']==arrays,'Parent array count changed')
    allowed={'execution.json','execution.json.tmp','input-validation.json','lineage'}|set(part['fixed_branch_ids'])
    require({p.name for p in output.iterdir()}<=allowed and all(not p.is_symlink() for p in output.rglob('*')),
            'Unexpected continuation evidence')
    complete=all(b['complete_diagnostic'] for b in checked)
    confirmed=sum(b['complete_diagnostic'] and b['status']=='confirmed' for b in checked)
    require(execution['status'] in ('prepared','running','completed','incomplete')
            and (execution['status']!='completed' or complete),'False partition completion claim')
    return {'status':'controls_confirmed' if complete and confirmed==len(rows) else 'complete_with_numerical_failures' if complete else 'incomplete',
        'index':index,'batch_index':part['batch_index'],'complete_selected_diagnostics':complete,
        'confirmed_branches':confirmed,'branches':checked,'verified_arrays':sum(b['verified_arrays'] for b in checked),
        'parent_arrays_preserved':arrays,'preserved_terminal_diagnostics':len(part['preserve_terminal_branch_ids']),
        'producer_status':execution['status'],
        'unverified_checkpoint_files':sorted(p.name for p in output.iterdir() if p.name.endswith('.tmp')),
        'execution_sha256':digest(output/'execution.json'),'case_recovery_claimed':False,
        'full_model_coverage_claimed':False,'numerical_integrations_performed':0}


def child(output,index,bid,context):
    part=inputs.selected_part(context,index)
    execution=read(output/'execution.json')
    require(bid in execution['work_order'] and execution['attempted_now'][-1:]==[bid]
            and execution['attempted_now']==execution['work_order'][:len(execution['attempted_now'])]
            and bid not in part['preserve_terminal_branch_ids'],'Branch is not the scheduled unfinished control')
    preservation(output,part)
    directory=output/bid
    directory.mkdir(exist_ok=True)
    require(not (directory/'audit.json').exists(),'A resumed child cannot overwrite an existing audit')
    plan,inventory,model,info,grid=context['scientific']
    report={'metadata':producer.metadata_for(plan),'record_id':bid,'plan_sha256':original.PLAN_SHA,
            'batch_index':part['batch_index'],'partition_index':index,'status':'running','branch':None,
            'source_revision':execution['source_revision'],'run_id':execution['run_id'],'run_attempt':execution['run_attempt'],
            'started_at':datetime.now(timezone.utc).isoformat()}
    write(directory/'report.json',report)
    row=producer.compute_branch(bid,inventory['branches'][bid],directory,report['metadata'],grid,model,info,resume=True)
    report.update(status='completed',branch=row,finished_at=datetime.now(timezone.utc).isoformat())
    write(directory/'report.json',report)


def compute(output,index,context,bundle,budget):
    require(type(budget) in (int,float) and math.isfinite(budget) and 0<budget<=19200,'Invalid computation budget')
    audit(output,index,context)
    execution=read(output/'execution.json')
    require(execution['status']=='prepared' and not execution['attempted_now'],'Use a fresh verified continuation')
    entries={e['record_id']:e for e in execution['branches']}
    rows={r['record_id']:r for r in context['plan']['partitions'][index]['branches']}
    deadline=time.monotonic()+budget
    for bid in execution['work_order']:
        if time.monotonic()>=deadline: break
        row=rows[bid]
        payload=4*row['sample_count']*(len(context['scientific'][3]['observables'])+1)*8
        if shutil.disk_usage(output).free<payload+512*1024**2:
            execution['stop_reason']='disk_limit';break
        entry=entries[bid];entry.clear();entry.update(row,status='running')
        execution['attempted_now'].append(bid);execution['status']='running'
        write(output/'execution.json',execution)
        command=[sys.executable,str(Path(__file__).resolve()),'child','--inputs',str(bundle.resolve()),
                 '--index',str(index),'--branch',bid,'--output',str(output.resolve())]
        try:
            process=subprocess.run(command,cwd=ROOT,timeout=max(.001,deadline-time.monotonic()))
            require(process.returncode==0,f'Child exited {process.returncode}')
            directory=output/bid;old=output/'lineage'/bid/(bid+'.json')
            checked=resumed.audit(directory,row,entry,context['scientific'],context['plan']['partitions'][index],identity_for(execution),
                parent_record=old if old.exists() else None,parent_record_sha256=digest(old) if old.exists() else None)
            require(checked['complete_diagnostic'],'Child returned without complete requested outcomes')
            write(directory/'audit.json',checked['continuation_audit'])
            entry.update(status='confirmed' if checked['status']=='confirmed' else 'numerical_failure',
                         report_sha256=digest(directory/'report.json'),audit_sha256=digest(directory/'audit.json'))
        except subprocess.TimeoutExpired:
            entry.update(status='time_limit',error='Computation budget exhausted; partial evidence retained')
        except Exception as error:
            entry.update(status='execution_or_audit_failure',error=f'{type(error).__name__}: {error}')
        write(output/'execution.json',execution)
        print({'partition':index,'record_id':bid,'status':entry['status']},flush=True)
    checked=audit(output,index,context)
    execution.update(status='completed' if checked['complete_selected_diagnostics'] else 'incomplete',
                     finished_at=datetime.now(timezone.utc).isoformat())
    write(output/'execution.json',execution)
    return 0 if checked['status']=='controls_confirmed' else 2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['check','artifact','restore','compute','child','audit'])
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--index',type=int)
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--audit-output',type=Path)
    parser.add_argument('--branch')
    parser.add_argument('--budget',type=float,default=19200)
    args=parser.parse_args()
    context=context_for(args.inputs)
    if args.operation=='check':
        print({'partitions':512,'continuations':len(context['requirements']['continue_indices']),
               'required_stage_branches':10924,'required_full_branches':11674,'cases':123});return 0
    part=inputs.selected_part(context,args.index)
    if args.operation=='artifact': print(part['parent_artifact_id']);return 0
    require(args.output is not None,'Output directory required')
    if args.operation=='restore':
        require(args.archive is not None and not args.output.exists(),'Original archive and new output required')
        identity={'id':int(os.environ['GITHUB_RUN_ID']),'run_attempt':int(os.environ['GITHUB_RUN_ATTEMPT']),
                  'head_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='rohwer-later-parent-') as tmp:
            evidence=Path(tmp)/'evidence'
            inputs.verify_parent(args.archive,evidence,args.index,context,context['scientific'],context['input_validation'])
            initialize(evidence,args.output,args.index,context,identity)
        audit(args.output,args.index,context);return 0
    if args.operation in ('compute','child'):
        execution=read(args.output/'execution.json')
        require(execution['run_id']==os.environ.get('GITHUB_RUN_ID')
                and execution['run_attempt']==os.environ.get('GITHUB_RUN_ATTEMPT')
                and execution['source_revision']==subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                'Computation must use the explicitly restored workflow identity')
        if args.operation=='compute':return compute(args.output,args.index,context,args.inputs,args.budget)
        child(args.output,args.index,args.branch,context);return 0
    require(args.audit_output is not None and not args.audit_output.exists(),'New audit output required')
    result=audit(args.output,args.index,context)
    write(args.audit_output,result)
    print({k:result[k] for k in ('status','index','verified_arrays','parent_arrays_preserved')})
    return 0


if __name__=='__main__':sys.exit(main())
