"""Bind all requested continuation jobs and route only terminal uploaded outputs.

Pending continuation jobs retain their audited original parents. The complete
512-partition selection and every original branch remain required throughout.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

from scripts import continue_rohwer_later as runner
from scripts.run_rohwer_later_controls import digest,read,require,write

ROOT=runner.ROOT
SOURCE_FILES=('scripts/rohwer_later_continuation_inputs.py','scripts/audit_rohwer_resumed_branch.py',
              'scripts/continue_rohwer_later.py','scripts/collect_rohwer_later_continuation.py',
              'scripts/audit_rohwer_full_cases.py')


def source_proof(revision):
    require(isinstance(revision,str) and re.fullmatch('[0-9a-f]{40}',revision),'Exact continuation revision required')
    ctx=runner.inputs.check_bindings()
    files=runner.inputs.capture.check_runtime(ctx['plan'])
    for name,sha in files.items():
        content=subprocess.check_output(['git','show',revision+':python/'+name],cwd=ROOT)
        require(hashlib.sha256(content).hexdigest()==sha,'Continuation changes frozen numerical source: '+name)
    checked={}
    for name in (*SOURCE_FILES,'scripts/collect_rohwer_later_controls.py'):
        content=subprocess.check_output(['git','show',revision+':python/'+name],cwd=ROOT)
        require(hashlib.sha256(content).hexdigest()==digest(ROOT/name),'Collector differs from selected source: '+name)
        checked[name]=digest(ROOT/name)
    # The collector was added after the original numerical producer. Its pinned
    # source revision is retained by the already-validated missing-output capture.
    base=runner.inputs.capture.FROZEN_COLLECTOR_REVISION
    frozen=subprocess.check_output(['git','show',base+':python/scripts/collect_rohwer_later_controls.py'],cwd=ROOT)
    require(hashlib.sha256(frozen).hexdigest()==checked['scripts/collect_rohwer_later_controls.py'],'Original collector changed')
    workflow=subprocess.check_output(['git','show',revision+':'+runner.WORKFLOW],cwd=ROOT)
    require(hashlib.sha256(workflow).hexdigest()==digest(ROOT.parent/runner.WORKFLOW),'Selected workflow source differs')
    return {'revision':revision,'frozen_numerical_files':ctx['plan']['runtime']['source_hashes'],
            'continuation_files':checked,'workflow_sha256':hashlib.sha256(workflow).hexdigest()}


def selected_indices(value,context=None):
    """Bound submission size without changing the full continuation inventory."""
    context=context or runner.inputs.check_bindings()
    indices=json.loads(value) if isinstance(value,str) else value
    require(isinstance(indices,list) and 1<=len(indices)<=4
            and all(type(i) is int for i in indices) and indices==sorted(set(indices))
            and set(indices)<=set(context['requirements']['continue_indices']),
            'Select one to four sorted unique eligible partition indices')
    return indices


def bind(run,jobs,revision,indices):
    ctx=runner.inputs.check_bindings()
    proof=source_proof(revision)
    indices=selected_indices(indices,ctx)
    require(run['head_sha']==revision and run['path']==runner.WORKFLOW and run['event']=='workflow_dispatch'
            and type(run['id']) is int and run['id']>0 and run['run_attempt']==1
            and type(run['workflow_id']) is int and run['workflow_id']>0
            and run['repository']['full_name']=='m9h/GRN_ODE','Selected continuation run identity differs')
    require(jobs['total_count']==len(jobs['jobs'])==len(indices)+1
            and len({j['id'] for j in jobs['jobs']})==len(jobs['jobs']), 'Complete unique continuation job pages required')
    names={'validation'}|{f'rohwer-later-continuation-{i}' for i in indices}
    require({j['name'] for j in jobs['jobs']}==names,'Exactly every requested unfinished partition is required')
    require(all(type(j['id']) is int and j['id']>0 and j['run_id']==run['id'] and j['run_attempt']==1
                and j['head_sha']==revision for j in jobs['jobs']),'Continuation job source or attempt differs')
    gate=next(j for j in jobs['jobs'] if j['name']=='validation')
    require(gate['status']=='completed' and gate['conclusion']=='success','Matching Linux validation must pass first')
    selected=deepcopy(ctx['selection']['selected'])
    for index in indices:
        job=next(j for j in jobs['jobs'] if j['name']==f'rohwer-later-continuation-{index}')
        parent=deepcopy(selected[index])
        selected[index].update(run_id=run['id'],job_id=job['id'],job_name=job['name'],previous=parent,
                               artifact_name=f'rohwer-controls-continuation-partition-{index}-attempt-1')
    require(sum(a==b for a,b in zip(selected,ctx['selection']['selected'],strict=True))==512-len(indices),'Original unaffected selections changed')
    return {'schema':1,'binding_sha256':runner.inputs.BINDING_SHA,'source_proof':proof,
            'run':{k:run[k] for k in ('id','run_attempt','workflow_id','head_sha','path')},
            'validation_job_id':gate['id'],'requested_indices':indices,'selected':selected,
            'required_continuation_indices':ctx['requirements']['continue_indices'],
            'eligible_indices_not_in_this_run':sorted(set(ctx['requirements']['continue_indices'])-set(indices)),
            'full_partitions':512,'required_stage_branches':10924,'required_full_branches':11674,'required_cases':123,
            'case_recovery_claimed':False,'full_model_coverage_claimed':False}


class Continuation:
    def __init__(self,descriptor):
        descriptor=Path(descriptor);value=read(descriptor)
        self.descriptor=descriptor.resolve()
        require(set(value)=={'binding','snapshots','cache'},'Continuation descriptor fields differ')
        self.paths={k:(descriptor.parent/v).resolve() for k,v in value.items()}
        self.binding=read(self.paths['binding'])
        self.run,self.jobs,self.artifacts=(read(self.paths['snapshots']/(n+'.json')) for n in ('run','jobs','artifacts'))
        require(self.binding==bind(self.run,self.jobs,self.binding['run']['head_sha'],self.binding['requested_indices']),'Full actual job binding differs')
        require(self.artifacts['total_count']==len(self.artifacts['artifacts'])
                and len({a['id'] for a in self.artifacts['artifacts']})==self.artifacts['total_count'],
                'Complete unique continuation artifact pages required')
        self.context=runner.inputs.check_bindings()
        self.indices=set(self.binding['requested_indices'])
        allowed={self.binding['selected'][i]['artifact_name'] for i in self.indices}
        require(all(a['name'] in allowed for a in self.artifacts['artifacts']),'Artifact outside complete continuation selection')

    def validate_original(self,selection,batches):
        require(selection==self.context['selection'] and len(batches)==2,'Both complete original batch selections required')

    def available(self,index):
        if index not in self.indices:return False
        row=self.binding['selected'][index]
        job=next(j for j in self.jobs['jobs'] if j['id']==row['job_id'])
        matches=[a for a in self.artifacts['artifacts'] if a['name']==row['artifact_name']]
        require(len(matches)<=1,'Duplicate continuation artifact')
        return job['status']=='completed' and bool(matches)

    def for_index(self,index):
        return self if index in self.indices else None

    def validate_job(self,row,run,job):
        require({k:run[k] for k in self.binding['run']}==self.binding['run']
                and row==self.binding['selected'][row['index']] and row['index'] in self.indices
                and job['id']==row['job_id'] and job['name']==row['job_name']
                and job['run_id']==run['id'] and job['run_attempt']==1 and job['head_sha']==run['head_sha'],
                'Selected continuation job differs')

    def validate_artifact(self,row,run,job,artifact):
        self.validate_job(row,run,job)
        require(type(artifact['id']) is int and artifact['id']>0 and artifact['name']==row['artifact_name']
                and artifact['expired'] is False and artifact['workflow_run']['id']==run['id']
                and artifact['workflow_run']['head_sha']==run['head_sha'],'Continuation artifact producer differs')
        require(job['status']=='completed' and job['completed_at']
                and datetime.fromisoformat(job['started_at'])<=datetime.fromisoformat(artifact['created_at'])
                <=datetime.fromisoformat(job['completed_at']),'Artifact is outside selected job attempt')
        require(re.fullmatch(r'sha256:[0-9a-f]{64}',artifact.get('digest',''))
                and type(artifact['size_in_bytes']) is int and artifact['size_in_bytes']>0,'Original archive checksum and size required')

    def verify_partition(self,evidence,row,scientific_context,runner_sha,input_validation):
        require(scientific_context[0]==self.context['plan'],'Frozen scientific context differs')
        require(runner_sha==self.binding['source_proof']['continuation_files'][runner.SCRIPT],'Continuation runner hash differs')
        ctx={**self.context,'scientific':scientific_context,'input_validation':input_validation}
        return runner.audit(evidence,row['index'],ctx,run=self.run,revision=self.run['head_sha'])

    def preserve(self,output):
        directory=output/'controls-continuation-provenance';directory.mkdir()
        sources={'binding.json':self.paths['binding'],
                 **{n+'.json':self.paths['snapshots']/(n+'.json') for n in ('run','jobs','artifacts')}}
        for name,path in sources.items():
            require(not path.is_symlink(),'Unsafe continuation provenance')
            (directory/name).write_bytes(path.read_bytes())
        available=[i for i in sorted(self.indices) if self.available(i)]
        return {'run':self.binding['run'],'validation_job_id':self.binding['validation_job_id'],
                'requested_indices':sorted(self.indices),'available_replacement_indices':available,
                'required_continuation_indices':self.binding['required_continuation_indices'],
                'eligible_indices_not_in_this_run':self.binding['eligible_indices_not_in_this_run'],
                'original_parents_retained_while_waiting':sorted(self.indices-set(available)),
                'full_partitions':512,'provenance_sha256':{n:digest(directory/n) for n in sources},
                'case_recovery_claimed':False,'full_model_coverage_claimed':False}


class ContinuationSet:
    """Combine disjoint bounded submissions without dropping any original row."""
    def __init__(self,descriptors):
        require(isinstance(descriptors,(list,tuple)) and descriptors,'Declare at least one continuation batch')
        self.members=[Continuation(path) for path in descriptors]
        self.indices=set()
        for member in self.members:
            require(not self.indices.intersection(member.indices),'Conflicting continuation batches')
            self.indices.update(member.indices)

    def for_index(self,index):
        return next((member for member in self.members if index in member.indices),None)

    def validate_original(self,selection,batches):
        for member in self.members: member.validate_original(selection,batches)

    def preserve(self,output):
        directory=output/'controls-continuation-batches';directory.mkdir()
        batches=[]
        for member in self.members:
            target=directory/str(member.run['id']);target.mkdir()
            batches.append(member.preserve(target))
        required=self.members[0].binding['required_continuation_indices']
        return {'batches':batches,'requested_indices':sorted(self.indices),
                'required_continuation_indices':required,
                'eligible_indices_not_submitted':sorted(set(required)-self.indices),
                'full_partitions':512,'required_full_branches':11674,'required_cases':123,
                'case_recovery_claimed':False,'full_model_coverage_claimed':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--jobs',type=Path,required=True)
    parser.add_argument('--revision',required=True)
    parser.add_argument('--indices',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    require(not args.output.exists(),'Use a new binding file')
    value=bind(read(args.run),read(args.jobs),args.revision,selected_indices(args.indices))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    write(args.output,value)
