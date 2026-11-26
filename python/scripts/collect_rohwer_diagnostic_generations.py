"""Route the complete first-stage inventory through frozen checkpoint auditors.

The first supplied generation must have all 32 original archives available.
Later incomplete generations retain that evidence until their outputs arrive.
An uploaded corrupt result is an error, never a reason to silently fall back.
No numerical integration or modification of producer evidence occurs here.
"""
from pathlib import Path
import hashlib
import subprocess

from scripts import collect_rohwer_checkpoint as checkpoints
from scripts.run_rohwer_breaking_diagnostics import digest,read,require,write

ROOT=checkpoints.ROOT
FROZEN_VALIDATORS='fcf7fd8cf975bc9171370e05789661d9da4d35b4'
VALIDATORS=('scripts/continue_rohwer_first.py','scripts/collect_rohwer_first_continuation.py',
            'scripts/continue_rohwer_checkpoint.py','scripts/collect_rohwer_checkpoint.py',
            'scripts/collect_rohwer_breaking_diagnostics.py')


def frozen_validators():
    hashes={}
    for name in VALIDATORS:
        content=subprocess.check_output(['git','show',FROZEN_VALIDATORS+':python/'+name],cwd=ROOT)
        expected=hashlib.sha256(content).hexdigest()
        require(not (ROOT/name).is_symlink() and digest(ROOT/name)==expected,'Frozen checkpoint validator differs: '+name)
        hashes[name]=expected
    return hashes


class Generation:
    def __init__(self,value,parent):
        require(set(value)=={'selection','snapshots','cache','bindings','binding_sha256'},'Generation descriptor fields differ')
        self.paths={k:(parent/value[k]).resolve() for k in ('selection','snapshots','cache')}
        bindings=(ROOT/value['bindings']).resolve()
        require(bindings.is_relative_to(ROOT.resolve()),'Checkpoint binding must be inside the frozen source tree')
        self.context=checkpoints.continuation.check_bindings(bindings,value['binding_sha256'])
        self.generation=self.context['binding']['generation']
        self.selection=read(self.paths['selection'])
        self.run,self.jobs,self.artifacts=(read(self.paths['snapshots']/(n+'.json')) for n in ('run','jobs','artifacts'))
        self.revision=self.selection['producer_revision']
        require(self.run['repository']['full_name']=='m9h/GRN_ODE','Checkpoint repository differs')
        require(self.selection==checkpoints.bind(self.context['plan'],self.run,self.jobs,self.revision,self.context),
                'Complete actual checkpoint job binding differs')
        require(self.artifacts['total_count']==len(self.artifacts['artifacts'])
                ==len({a['id'] for a in self.artifacts['artifacts']}),'Complete unique artifact pages required')
        allowed={r['artifact_name'] for r in self.selection['selected']}
        names=[a['name'] for a in self.artifacts['artifacts']]
        require(set(names)<=allowed and len(names)==len(set(names)),'Unexpected or duplicate checkpoint artifact')
        # The selected producer must contain this exact immutable binding. Its
        # recursive parent bindings and numerical environment were checked above.
        binding_source=subprocess.check_output(['git','show',self.revision+':python/'+
                        bindings.relative_to(ROOT).as_posix()+'/binding.json'],cwd=ROOT)
        require(hashlib.sha256(binding_source).hexdigest()==value['binding_sha256'],
                'Selected producer used a different checkpoint binding')
        self.runner_sha=checkpoints.continuation.source_hash(self.revision)
        self.sources={'selection.json':self.paths['selection'],
                      **{n+'.json':self.paths['snapshots']/(n+'.json') for n in ('run','jobs','artifacts')}}
        self.source_hashes={n:digest(p) for n,p in self.sources.items()}

    def available(self,index):
        row=self.selection['selected'][index]
        job=next(j for j in self.jobs['jobs'] if j['id']==row['job_id'])
        matches=[a for a in self.artifacts['artifacts'] if a['name']==row['artifact_name']]
        return job['status']=='completed' and bool(matches)

    def validate_job(self,row,run,job):
        require(row==self.selection['selected'][row['index']] and run==self.run,'Selected checkpoint generation differs')
        checkpoints.validate_job(row,run,job)

    def validate_artifact(self,row,run,job,artifact):
        self.validate_job(row,run,job)
        checkpoints.validate_artifact(row,run,job,artifact)

    def verify_partition(self,evidence,row,inputs,plan,runner_sha):
        require(plan==self.context['plan'] and runner_sha==self.runner_sha,'Frozen diagnostic plan or runner differs')
        checked=checkpoints.continuation.audit(evidence,row['index'],plan,self.context,inputs,
                    revision=self.revision,run_id=str(self.run['id']),run_attempt='1')
        # Adapt only the wrapper-status field needed by the existing full-case
        # collector. Branch windows/comparisons and completion are unchanged.
        checked['producer_status']=read(evidence/'execution.json')['status']
        checked['unverified_checkpoint_files']=[]
        return checked


class DiagnosticGenerations:
    def __init__(self,descriptor):
        self.descriptor=Path(descriptor).resolve()
        value=read(self.descriptor)
        require(set(value)=={'generations'} and isinstance(value['generations'],list)
                and value['generations'],'Declare the complete checkpoint generation chain')
        self.validator_hashes=frozen_validators()
        self.members=[Generation(v,self.descriptor.parent) for v in value['generations']]
        generations=[m.generation for m in self.members]
        require(generations==list(range(2,2+len(generations))),'Supply consecutive generations beginning with generation 2')
        require(all(self.members[0].available(i) for i in range(32)),
                'The base checkpoint generation must retain all 32 available original partitions')
        for parent,child in zip(self.members,self.members[1:]):
            binding=child.context['binding']
            require(binding['parent_run_id']==parent.run['id'] and binding['parent_revision']==parent.revision
                    and binding['parent_context']['sha256']==parent.context['binding_sha256']
                    and child.context['selection']==parent.selection,'Checkpoint ancestry or full parent selection differs')
            expected={a['id']:a for a in child.context['artifacts']['artifacts']}
            actual={a['id']:a for a in parent.artifacts['artifacts']}
            require(set(actual)==set(expected) and all(all(actual[i][k]==expected[i][k]
                    for k in ('name','digest','size_in_bytes','workflow_run')) for i in expected),
                    'Actual parent archive identities differ from the child binding')
        self.descriptor_sha256=digest(self.descriptor)
        self.indices=set(range(32))

    def for_index(self,index):
        require(type(index) is int and 0<=index<32,'Invalid original diagnostic partition')
        return next(m for m in reversed(self.members) if m.available(index))

    def validate_original(self,selection,batches,plan):
        first=checkpoints.continuation.first
        original=read(first.BINDINGS/'selection.json')
        require(selection==original and len(batches)==1
                and all(m.context['plan']==plan for m in self.members),
                'The complete original first-stage selection and frozen plan remain required')

    def assert_unchanged(self):
        require(digest(self.descriptor)==self.descriptor_sha256,'Generation descriptor changed during audit')
        for member in self.members:
            require(all(digest(p)==member.source_hashes[n] for n,p in member.sources.items()),
                    'Checkpoint API or selection changed during audit')

    def preserve(self,output):
        root=output/'diagnostic-generation-provenance';root.mkdir()
        (root/'descriptor.json').write_bytes(self.descriptor.read_bytes())
        members=[]
        for member in self.members:
            directory=root/str(member.generation);directory.mkdir()
            for name,path in member.sources.items():
                require(not path.is_symlink(),'Unsafe checkpoint source snapshot')
                (directory/name).write_bytes(path.read_bytes())
            members.append({'generation':member.generation,'run_id':member.run['id'],
                'producer_revision':member.revision,'binding_sha256':member.context['binding_sha256'],
                'runner_sha256':member.runner_sha,'source_sha256':member.source_hashes,
                'available_indices':[i for i in range(32) if member.available(i)]})
        chosen=[{'index':i,'generation':self.for_index(i).generation,'run_id':self.for_index(i).run['id'],
                 'job_id':self.for_index(i).selection['selected'][i]['job_id']} for i in range(32)]
        self.assert_unchanged()
        return {'generations':members,'selected':chosen,'original_partitions':32,'required_stage_branches':750,
                'required_full_branches':11674,'required_cases':123,
                'frozen_validator_revision':FROZEN_VALIDATORS,'frozen_validator_sha256':self.validator_hashes,
                'descriptor_sha256':self.descriptor_sha256,'numerical_integrations_performed':0,
                'case_recovery_claimed':False,'full_model_coverage_claimed':False}
