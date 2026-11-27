"""Bind and audit all 41 original cloud jobs from saved API snapshots and ZIPs.

This offline collector never dispatches jobs or performs integrations. Pending,
missing, interrupted and numerically failed outputs remain separate outcomes.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from grn_memory import francois_native_capture as work
require,read,digest=work.require,work.read,work.digest
WORKFLOW='.github/workflows/francois-native-capture.yml'
BRANCH='kinetics-francois-copasi-capture'
ALLOWED={'execution.json','protocol.xml','roadrunner.npz','copasi.npz','copasi-raw.npz','copasi-raw.log.gz','audit.json'}

def inventory(data,key):
    require(type(data['total_count']) is int and data['total_count']==len(data[key]) and
            len({v['id'] for v in data[key]})==len(data[key]),'Complete unique API inventory required: '+key)
    return data[key]

def bind(run,jobs,revision):
    require(bool(re.fullmatch('[0-9a-f]{40}',revision)) and run['head_sha']==revision and run['path']==WORKFLOW and
            run['head_branch']==BRANCH and run['event']=='workflow_dispatch' and type(run['id']) is int and run['id']>0 and
            type(run['run_attempt']) is int and run['run_attempt']>0,'Frozen workflow identity differs')
    rows=inventory(jobs,'jobs')
    names={'validation',*(f'francois-native-branch-{i}' for i in range(41))}
    require(len(rows)==42 and {j['name'] for j in rows}==names,'Bind all 41 actual branch jobs after the gate passes')
    for job in rows:
        require(type(job['id']) is int and job['id']>0 and job['run_id']==run['id'] and job['run_attempt']==run['run_attempt'] and job['head_sha']==revision,'Job producer identity differs')
    gate=next(j for j in rows if j['name']=='validation')
    require(gate['status']=='completed' and gate['conclusion']=='success','Matching Linux validation gate must pass')
    plan=work.context()[0]
    selected=[]
    for index,bid in enumerate(plan['ordered_branch_ids']):
        job=next(j for j in rows if j['name']==f'francois-native-branch-{index}')
        selected.append({'index':index,'record_id':bid,'job_id':job['id'],
            'artifact_name':f'francois-native-branch-{index}-attempt-{run["run_attempt"]}'})
    return {'schema':1,'repository':'m9h/GRN_ODE','workflow':WORKFLOW,'source_revision':revision,
        'run_id':run['id'],'run_attempt':run['run_attempt'],'gate_job_id':gate['id'],
        'plan_sha256':work.PLAN_SHA,'full_original_cases':118,'required_branches':41,
        'required_trials':6,'selected':selected}

def validate_artifact(artifact,row,selection):
    require(artifact['name']==row['artifact_name'] and artifact['expired'] is False and
            type(artifact['size_in_bytes']) is int and artifact['size_in_bytes']>0 and
            bool(re.fullmatch('sha256:[0-9a-f]{64}',artifact['digest'])),'Selected original artifact identity differs')
    run=artifact['workflow_run']
    require(run['id']==selection['run_id'] and run['head_sha']==selection['source_revision'],'Artifact producer differs')

def extract(archive,destination):
    require(not destination.exists(),'Use a fresh extraction directory')
    destination.mkdir(parents=True)
    with zipfile.ZipFile(archive) as zipped:
        members=zipped.infolist()
        require(len({i.filename for i in members})==len(members),'Duplicate ZIP member')
        require(sum(i.file_size for i in members)<=1024**3,'Unexpectedly large branch payload; preserve ZIP for separate inspection')
        for item in members:
            require(item.filename in ALLOWED and not item.is_dir() and not stat.S_ISLNK(item.external_attr>>16),'Unsafe or unexpected archive member')
        for item in members:
            with zipped.open(item) as src,(destination/item.filename).open('xb') as dst:
                shutil.copyfileobj(src,dst)
    require((destination/'execution.json').is_file(),'Missing execution record')
    return {p.name:digest(p) for p in sorted(destination.iterdir())}

def collect(selection,api,archives,output):
    require(not output.exists(),'Use a fresh collection; preserve all earlier audits')
    run,jobs,artifacts=(read(api/(n+'.json')) for n in ('run','jobs','artifacts'))
    require(bind(run,jobs,selection['source_revision'])==selection,'Full selected job binding changed')
    available=inventory(artifacts,'artifacts');ctx=work.context()
    output.mkdir(parents=True)
    for name in ('run','jobs','artifacts'):shutil.copyfile(api/(name+'.json'),output/(name+'.json'))
    work.write(output/'selection.json',selection)
    audited=[];pending=[];missing=[];interrupted=[];errors=[]
    for row in selection['selected']:
        index=row['index'];job=next(j for j in jobs['jobs'] if j['id']==row['job_id'])
        if job['status']!='completed':pending.append(index);continue
        matches=[a for a in available if a['name']==row['artifact_name']]
        if not matches:missing.append({'index':index,'job_conclusion':job['conclusion']});continue
        try:
            require(len(matches)==1,'Duplicate selected artifact')
            artifact=matches[0];validate_artifact(artifact,row,selection)
            archive=archives/f'artifact-{artifact["id"]}.zip'
            require(archive.is_file() and not archive.is_symlink() and archive.stat().st_size==artifact['size_in_bytes'] and
                    'sha256:'+digest(archive)==artifact['digest'],'Original ZIP bytes differ')
            directory=output/f'branch-{index}'
            files=extract(archive,directory)
            execution=read(directory/'execution.json')
            provenance={**row,'artifact_id':artifact['id'],'archive_sha256':artifact['digest'],
                        'archive_bytes':artifact['size_in_bytes'],'original_zip':str(archive.resolve()),
                        'evidence':str(directory.resolve()),'evidence_sha256':files,'job_conclusion':job['conclusion']}
            require(execution['plan_sha256']==work.PLAN_SHA and execution['index']==index and execution['record_id']==row['record_id'] and
                    execution['source_revision']==selection['source_revision'],'Produced output identity differs')
            if execution['status']!='completed':
                interrupted.append({**provenance,'producer_status':execution['status']});continue
            result=work.audit_result(directory,index,ctx,expected_revision=selection['source_revision'])
            if (directory/'audit.json').exists():
                require(read(directory/'audit.json')==result,'Cloud and local independent audits differ')
            work.write(directory/'independent-audit.json',result)
            audited.append({**provenance,**result})
        except Exception as error:
            errors.append({'index':index,'error':f'{type(error).__name__}: {error}'})
    complete=len(audited)==41 and not (pending or missing or interrupted or errors)
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'plan_sha256':work.PLAN_SHA,
        'source_revision':selection['source_revision'],'run_id':selection['run_id'],
        'full_original_cases':118,'required_branches':41,'required_trials':6,
        'complete_native_attempt_coverage':complete,'verified_complete_arrays':sum(r['verified_complete_arrays'] for r in audited),
        'audited_branches':audited,'pending_indices':pending,'missing_artifacts':missing,
        'interrupted_outputs':interrupted,'collection_errors':errors,
        'selected_trial_audit':work.replay_trials(audited,ctx) if complete else None,
        'collector_sha256':digest(Path(__file__)),'case_recovery_claimed':False,'whole_model_pass_claimed':False,
        'local_numerical_integrations_performed':0,'goal_complete':False}
    work.write(output/'collection.json',result)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api',type=Path,required=True)
    parser.add_argument('--bind',action='store_true')
    parser.add_argument('--revision')
    parser.add_argument('--selection',type=Path)
    parser.add_argument('--archives',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.bind:
        if not args.revision:parser.error('--bind requires the frozen --revision')
        require(not args.output.exists(),'Do not overwrite a previous selection')
        value=bind(read(args.api/'run.json'),read(args.api/'jobs.json'),args.revision)
        work.write(args.output,value);print(json.dumps({'required_branches':41,'bound_jobs':len(value['selected']),'run_id':value['run_id']}))
    else:
        if not args.selection or not args.archives:parser.error('--selection and --archives are required')
        value=collect(read(args.selection),args.api,args.archives,args.output)
        print(json.dumps({k:v for k,v in value.items() if k not in ('audited_branches','selected_trial_audit','interrupted_outputs')}))
