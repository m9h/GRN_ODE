"""Recover one missing Rohwer archive without narrowing either original batch.

The existing numerical producer, array collector and case mathematics remain
unchanged. Only an isolated collector instance receives the new producer identity.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import json

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import collect_rohwer_later_controls as original
from scripts import run_rohwer_later_controls as producer
from scripts.run_rohwer_later_controls import read, write, digest, require

INPUTS=ROOT/'results/catalog-breaking-rohwer-missing-output-20261126'
CAPTURE_SHA='ac59ea2cdd6294282a42979a806df8cdf139259fe6e4b52468ba48194d60c4bd'
PLAN=ROOT/'results/catalog-breaking-rohwer-later-controls-20261118/plan.json'
WORKFLOW='.github/workflows/rohwer-missing-output-recovery.yml'
SCRIPT='scripts/rohwer_missing_output.py'
FROZEN_COLLECTOR_REVISION='602c34a0db23b2a75ee5a1a9aefe6caf8524d992'
DEPENDENCY_FILES={'jaxkineticmodel/load_sbml/'+name for name in (
    'sbml_model.py','jax_kinetic_model.py','sympy_converter.py','export_sbml.py','sbml_load_utils.py')}


def check_runtime(plan):
    require(producer.runtime()==plan['runtime'],'Frozen numerical source or installed runtime changed')
    files=plan['runtime']['source_hashes']
    require({n for n in files if n.startswith('jaxkineticmodel/')}==DEPENDENCY_FILES
            and {'pyproject.toml','uv.lock'}<=set(files),'Frozen dependency inventory differs')
    return {name:sha for name,sha in files.items() if name not in DEPENDENCY_FILES}


def validate_missing(row,run,jobs,artifacts):
    require(jobs['total_count']==len(jobs['jobs']) and artifacts['total_count']==len(artifacts['artifacts']),
            'All original API pages required')
    require(row['index']==23 and row['batch_index']==0 and row['job_id']==135270755047,
            'Wrong missing original job')
    matches=[j for j in jobs['jobs'] if j['id']==row['job_id']]
    require(len(matches)==1,'Missing original job identity')
    job=matches[0]
    original.validate_job(row,run,job)
    require(job['status']=='completed' and job['conclusion']=='failure','Do not replace a live original job')
    require(not any(a['name']==row['artifact_name'] for a in artifacts['artifacts']),
            'An original artifact exists; audit it instead of selecting a replacement')


def check_capture():
    require(digest(INPUTS/'recovery-plan.json')==CAPTURE_SHA,'Pinned recovery capture differs')
    capture=read(INPUTS/'recovery-plan.json')
    expected={'original-selection.json','missing-partition23-annotations.json'} | {
        f'original-api/batch-{b}/{n}.json' for b in range(2) for n in ('run','jobs','artifacts')}
    require(set(capture['files'])==expected,'Complete original capture inventory differs')
    for name,sha in capture['files'].items():
        require(not (INPUTS/name).is_symlink() and digest(INPUTS/name)==sha,'Original captured bytes differ: '+name)
    require(capture['repository']=='m9h/GRN_ODE' and capture['full_partitions']==512
            and capture['required_stage_branches']==10924 and capture['required_full_branches']==11674
            and capture['required_cases']==123 and capture['missing_indices']==[23]
            and capture['missing_job_ids']==[135270755047]
            and capture['case_recovery_claimed'] is False and capture['full_model_coverage_claimed'] is False,
            'Recovery cannot narrow the scientific scope')
    require(digest(PLAN)==capture['plan_sha256']==original.PLAN_SHA,'Original execution plan differs')
    plan,selection=read(PLAN),read(INPUTS/'original-selection.json')
    batches=[{n:read(INPUTS/f'original-api/batch-{b}/{n}.json') for n in ('run','jobs','artifacts')} for b in range(2)]
    require(original.bind_selection(plan,[b['run'] for b in batches],[b['jobs'] for b in batches])==selection,
            'Full original job selection differs')
    artifacts=[]
    for batch in batches:
        value=batch['artifacts']
        require(value['total_count']==len(value['artifacts']),'Complete original artifact pages required')
        artifacts.extend(value['artifacts'])
    require(len(artifacts)==len({a['id'] for a in artifacts})==capture['captured_original_archives']
            and sum(a['size_in_bytes'] for a in artifacts)==capture['captured_original_archive_bytes'],
            'Complete unique original archive inventory differs')
    missing=[]
    for row in selection['selected']:
        batch=batches[row['batch_index']]
        job=next(j for j in batch['jobs']['jobs'] if j['id']==row['job_id'])
        matches=[a for a in batch['artifacts']['artifacts'] if a['name']==row['artifact_name']]
        require(len(matches)<=1,'Duplicate original partition archive')
        if matches: original.validate_artifact(row,batch['run'],job,matches[0])
        elif job['status']=='completed': missing.append(row['index'])
    require(missing==[23],'Every terminal missing output must remain explicit')
    validate_missing(selection['selected'][23],**batches[0])
    require(any('lost communication' in n['message'] for n in read(INPUTS/'missing-partition23-annotations.json')),
            'Original runner-loss annotation required')
    check_runtime(plan)
    return capture,plan,selection


def indices(value):
    chosen=json.loads(value)
    require(chosen==[23] and type(chosen[0]) is int,'Only the pinned missing partition 23 may be dispatched')
    return chosen


def source_proof(revision):
    require(isinstance(revision,str) and re.fullmatch('[0-9a-f]{40}',revision),'Exact recovery revision required')
    _,plan,_=check_capture()
    for name,sha in check_runtime(plan).items():
        content=subprocess.check_output(['git','show',revision+':python/'+name],cwd=ROOT)
        require(hashlib.sha256(content).hexdigest()==sha,'Recovery revision changes frozen source: '+name)
    collector='scripts/collect_rohwer_later_controls.py'
    frozen=subprocess.check_output(['git','show',FROZEN_COLLECTOR_REVISION+':python/'+collector],cwd=ROOT)
    require(hashlib.sha256(frozen).hexdigest()==digest(ROOT/collector),'Original array collector changed')
    for name in (SCRIPT,collector):
        content=subprocess.check_output(['git','show',revision+':python/'+name],cwd=ROOT)
        require(hashlib.sha256(content).hexdigest()==digest(ROOT/name),'Use exact recovery collector source')
    workflow=subprocess.check_output(['git','show',revision+':'+WORKFLOW],cwd=ROOT)
    require(hashlib.sha256(workflow).hexdigest()==digest(ROOT.parent/WORKFLOW),'Recovery workflow source differs')
    return {'revision':revision,'frozen_numerical_files':dict(plan['runtime']['source_hashes']),
            'original_collector_sha256':digest(ROOT/collector),'recovery_collector_sha256':digest(ROOT/SCRIPT),
            'workflow_sha256':hashlib.sha256(workflow).hexdigest()}


def bind(run,jobs,revision):
    _,_,selection=check_capture()
    proof=source_proof(revision)
    require(run['head_sha']==revision and run['path']==WORKFLOW and run['event']=='workflow_dispatch'
            and type(run['id']) is int and run['id']>0 and run['run_attempt']==1
            and type(run['workflow_id']) is int and run['workflow_id']>0
            and run['repository']['full_name']=='m9h/GRN_ODE','Explicit recovery run, attempt or source differs')
    require(jobs['total_count']==len(jobs['jobs'])==2 and len({j['id'] for j in jobs['jobs']})==2,
            'Exactly the validation gate and one recovery job are required')
    require(all(type(j['id']) is int and j['id']>0 and j['run_id']==run['id']
                and j['run_attempt']==1 and j['head_sha']==revision for j in jobs['jobs']),
            'Recovery job source or attempt differs')
    gates=[j for j in jobs['jobs'] if j['name']=='validation']
    require(len(gates)==1 and gates[0]['status']=='completed' and gates[0]['conclusion']=='success',
            'Matching Linux validation must pass before binding recovery')
    selected=deepcopy(selection['selected'])
    row=deepcopy(selected[23])
    matches=[j for j in jobs['jobs'] if j['name']==row['job_name']]
    require(len(matches)==1,'Actual partition-23 recovery job required')
    row.update(job_id=matches[0]['id'],run_id=run['id'],previous=selected[23])
    selected[23]=row
    require(sum(a==b for a,b in zip(selected,selection['selected'],strict=True))==511,
            'Every other original selection must remain identical')
    return {'schema':1,'repository':'m9h/GRN_ODE','capture_sha256':CAPTURE_SHA,
            'original_selection_sha256':digest(INPUTS/'original-selection.json'),
            'recovery_run':{k:run[k] for k in ('id','run_attempt','workflow_id','head_sha','path')},
            'validation_job_id':gates[0]['id'],'source_proof':proof,'selected':selected,
            'full_partitions':512,'required_stage_branches':10924,'required_full_branches':11674,'required_cases':123,
            'case_recovery_claimed':False,'full_model_coverage_claimed':False}


def isolated_collector(run):
    spec=importlib.util.spec_from_file_location('_rohwer_missing_output_bound',Path(original.__file__))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.RUNS=deepcopy(original.RUNS)
    module.RUNS[0]={k:run[k] for k in ('id','run_attempt','workflow_id','head_sha','path')}
    return module


class Recovery:
    def __init__(self,descriptor):
        descriptor=Path(descriptor)
        value=read(descriptor)
        require(set(value)=={'binding','snapshots','cache'},'Recovery evidence paths differ')
        self.paths={k:(descriptor.parent/v).resolve() for k,v in value.items()}
        self.binding=read(self.paths['binding'])
        self.run,self.jobs,self.artifacts=(read(self.paths['snapshots']/(n+'.json')) for n in ('run','jobs','artifacts'))
        require(self.binding==bind(self.run,self.jobs,self.binding['recovery_run']['head_sha']),
                'Full recovery binding differs from actual jobs')
        require(self.artifacts['total_count']==len(self.artifacts['artifacts'])
                and len({a['id'] for a in self.artifacts['artifacts']})==self.artifacts['total_count'],
                'Complete unique recovery artifact inventory required')
        self.module=isolated_collector(self.run)
        self.row=self.binding['selected'][23]
        self.job=next(j for j in self.jobs['jobs'] if j['id']==self.row['job_id'])
        self.module.validate_job(self.row,self.run,self.job)
        self.runner_sha=self.binding['source_proof']['frozen_numerical_files']['scripts/run_rohwer_later_controls.py']

    def validate_original(self,selection,batches):
        _,_,pinned=check_capture()
        require(selection==pinned and len(batches)==2,'Original full selection changed before replacement')
        validate_missing(selection['selected'][23],**batches[0])

    def preserve(self,output):
        directory=output/'recovery-provenance'
        directory.mkdir()
        sources={'binding.json':self.paths['binding'],
                 **{n+'.json':self.paths['snapshots']/(n+'.json') for n in ('run','jobs','artifacts')}}
        for name,path in sources.items():
            require(not path.is_symlink(),'Recovery provenance cannot be a symlink')
            (directory/name).write_bytes(path.read_bytes())
        return {'recovery_run':self.binding['recovery_run'],'validation_job_id':self.binding['validation_job_id'],
                'replaced_indices':[23],'unchanged_original_selections':511,
                'provenance_sha256':{n:digest(directory/n) for n in sources},
                'original_missing_job_id':135270755047,'full_partitions':512,
                'case_recovery_claimed':False,'full_model_coverage_claimed':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=['check','matrix','bind'])
    p.add_argument('--runtime',action='store_true')
    p.add_argument('--inputs',type=Path)
    p.add_argument('--indices',default='[23]')
    for name in ('run','jobs','output'): p.add_argument('--'+name,type=Path)
    p.add_argument('--revision')
    args=p.parse_args()
    capture,_,_=check_capture()
    if args.runtime:
        require(args.inputs is not None,'Authenticated complete inputs required')
        producer.load_plan(PLAN,original.PLAN_SHA,args.inputs)
        source_proof(subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    if args.operation=='matrix': print(json.dumps({'index':indices(args.indices)},separators=(',',':')))
    elif args.operation=='bind':
        require(args.run is not None and args.jobs is not None and args.revision is not None
                and args.output is not None and not args.output.exists(),'Exact run, jobs, source and new binding required')
        result=bind(read(args.run),read(args.jobs),args.revision)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        write(args.output,result)
    else: print(json.dumps({'full_partitions':512,'later_controls':10924,'full_branches':11674,'cases':123,
                           'recovery_indices':capture['missing_indices'],'original_archives':232,
                           'numerical_integrations_performed':0}))


if __name__=='__main__': main()
