"""Generation selection and independent full-grid audits, without integrations."""
import ast
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import zipfile

import pytest

from scripts import collect_rohwer_diagnostic_generations as generations
from scripts import audit_rohwer_generation_cases as full
from scripts import audit_rohwer_full_cases as previous
from test_rohwer_later_controls import context
from test_rohwer_full_case_audit import diagnostic_synthetic,diagnostic_stage_fixture
from test_rohwer_checkpoint_continuation import next_generation

checkpoint=generations.checkpoints.continuation
read,write=generations.read,generations.write
CAPTURE=generations.ROOT/'results/catalog-breaking-rohwer-generation-case-audit-20261126'


@pytest.fixture(scope='module')
def contexts():
    return {2:checkpoint.check_bindings(check_runtime=False),
            3:checkpoint.check_bindings(generations.ROOT/'results/catalog-breaking-rohwer-checkpoint-continuation-20261125',
                '700ff6ac98c8caf12111527e508b6cc8a0f803a2068f2eaa3cf22c714960bb76',check_runtime=False)}


@pytest.fixture
def chain(tmp_path,monkeypatch,contexts):
    descriptors=[]
    for gen in (2,3):
        directory=tmp_path/str(gen);(directory/'api').mkdir(parents=True)
        source=generations.ROOT/'results/catalog-breaking-rohwer-checkpoint-continuation-20261125' if gen==2 else CAPTURE
        for name in ('selection.json','api/run.json','api/jobs.json','api/artifacts.json'):
            shutil.copyfile(source/name,directory/name)
        descriptors.append({'selection':f'{gen}/selection.json','snapshots':f'{gen}/api','cache':f'{gen}/cache',
            'bindings':f'results/catalog-breaking-rohwer-checkpoint-continuation-202611{24 if gen==2 else 25}',
            'binding_sha256':contexts[gen]['binding_sha256']})
    # These fixtures already authenticate the immutable recursive bindings above.
    # Installed runtime/source validation also runs separately on the real inputs.
    monkeypatch.setattr(checkpoint,'check_bindings',lambda path,sha:
        deepcopy(contexts[2 if Path(path).name.endswith('1124') else 3]))
    descriptor=tmp_path/'generations.json';write(descriptor,{'generations':descriptors})
    return descriptor


def test_frozen_validators_and_case_math_are_unchanged():
    assert len(generations.frozen_validators())==5
    def definitions(module):
        return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(Path(module.__file__).read_text()).body
                if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    before,after=definitions(previous),definitions(full)
    for name in ('scope','BranchStore','stage_snapshots','preserve_snapshots','replay','discrepancies'):
        assert before[name]==after[name]
    original=subprocess.check_output(['git','show','762d8812b516c10e90892a230a0baee3423988b6:python/scripts/audit_rohwer_full_cases.py'],cwd=generations.ROOT)
    assert Path(previous.__file__).read_bytes()==original


def test_complete_750_branch_chain_selects_17_new_and_15_retained_partitions(chain):
    selected=generations.DiagnosticGenerations(chain)
    assert [m.generation for m in selected.members]==[2,3]
    assert sum(selected.for_index(i).generation==3 for i in range(32))==17
    rows=[selected.for_index(i).selection['selected'][i] for i in range(32)]
    assert len({b['record_id'] for row in rows for b in row['branches']})==750
    output=chain.parent/'audit';output.mkdir()
    proof=selected.preserve(output)
    assert len(proof['selected'])==32 and proof['required_full_branches']==11674
    assert proof['required_cases']==123 and not proof['full_model_coverage_claimed']


@pytest.mark.parametrize('change',['missing_base','duplicate_generation','reverse','branch','job_pages','gate',
                                 'source','attempt','repository','binding','artifact_pages','artifact_name',
                                 'duplicate_artifact','missing_base_artifact','base_queued'])
def test_invalid_ancestry_scope_or_actual_identity_rejected(chain,change):
    descriptor=read(chain)
    if change in ('missing_base','duplicate_generation','reverse','binding'):
        if change=='missing_base':descriptor['generations'].pop(0)
        elif change=='duplicate_generation':descriptor['generations'].append(deepcopy(descriptor['generations'][-1]))
        elif change=='reverse':descriptor['generations'].reverse()
        else:descriptor['generations'][0]['binding_sha256']='0'*64
        write(chain,descriptor)
    else:
        filename='selection.json' if change=='branch' else 'api/run.json' if change in ('source','attempt','repository') else 'api/jobs.json' if change in ('job_pages','gate','base_queued') else 'api/artifacts.json'
        path=chain.parent/'2'/filename;value=read(path)
        if change=='branch':value['selected'][0]['branches'].pop()
        elif change=='job_pages':value['jobs'].pop()
        elif change=='gate':next(j for j in value['jobs'] if j['name']=='validation')['conclusion']='failure'
        elif change=='source':value['head_sha']='a'*40
        elif change=='attempt':value['run_attempt']=2
        elif change=='repository':value['repository']['full_name']='different/repo'
        elif change=='artifact_pages':value['total_count']+=1
        elif change=='artifact_name':value['artifacts'][0]['name']='different'
        elif change=='duplicate_artifact':value['artifacts'].append(deepcopy(value['artifacts'][0]));value['total_count']+=1
        elif change=='missing_base_artifact':value['artifacts'].pop();value['total_count']-=1
        else:next(j for j in value['jobs'] if j['name']!='validation')['status']='queued'
        write(path,value)
    with pytest.raises((ValueError,KeyError)):generations.DiagnosticGenerations(chain)


@pytest.mark.parametrize('state',['running_with_artifact','terminal_no_artifact'])
def test_pending_new_generation_retains_full_parent_selection(chain,state):
    jobs_path=chain.parent/'3/api/jobs.json';artifacts_path=chain.parent/'3/api/artifacts.json'
    jobs,artifacts=read(jobs_path),read(artifacts_path)
    selection=read(chain.parent/'3/selection.json');row=selection['selected'][0]
    job=next(j for j in jobs['jobs'] if j['id']==row['job_id'])
    if state=='running_with_artifact':job.update(status='in_progress',conclusion=None)
    else:
        artifacts['artifacts']=[a for a in artifacts['artifacts'] if a['name']!=row['artifact_name']]
        artifacts['total_count']=len(artifacts['artifacts'])
    write(jobs_path,jobs);write(artifacts_path,artifacts)
    selected=generations.DiagnosticGenerations(chain)
    assert selected.for_index(0).generation==2
    assert sum(selected.for_index(i).generation==3 for i in range(32))==16


def test_source_snapshot_mutation_during_collection_is_rejected(chain):
    selected=generations.DiagnosticGenerations(chain)
    with (chain.parent/'3/api/jobs.json').open('a') as stream:stream.write(' ')
    with pytest.raises(ValueError,match='changed during audit'):selected.assert_unchanged()


@pytest.mark.parametrize('change',[None,'array','lineage','source'])
def test_full_case_route_reaudits_checkpoint_arrays_and_retains_all_other_branches(
        diagnostic_synthetic,context,tmp_path,change):
    paths,plan,output,store,destination,row=diagnostic_stage_fixture(diagnostic_synthetic,context,tmp_path)
    parent=destination/'evidence'
    checked=previous.first.verify_partition(parent,row,previous.FIRST_INPUTS,plan,
        read(parent/'execution.json')['runner_sha256'])
    hashes={p.relative_to(parent).as_posix():generations.digest(p) for p in parent.rglob('*') if p.is_file()}
    part={'index':0,'parent_job_id':row['job_id'],'parent_artifact_id':42,'parent_archive_sha256':'sha256:'+'a'*64,
          'parent_execution_sha256':hashes['execution.json'],'parent_evidence_sha256':hashes,
          'fixed_branch_ids':[b['record_id'] for b in row['branches']],
          'preserve_complete_branch_ids':[b['record_id'] for b in checked['branches'] if b['complete_diagnostic']],
          'resume_partial_branch_ids':[],
          'unattempted_branch_ids':[b['record_id'] for b in checked['branches'] if b['status']=='not_started']}
    first=tmp_path/'first';checkpoint.first.initialize(parent,first,0,plan,{'partitions':[part]})
    first_checked=checkpoint.first.audit(first,0,plan,{'partitions':[part]},previous.FIRST_INPUTS)
    current,ctx=next_generation(first,plan,first_checked,2)
    run={'id':99999,'run_attempt':1,'head_sha':generations.FROZEN_VALIDATORS,'path':generations.checkpoints.WORKFLOW}
    execution=read(current/'execution.json');execution.update(producer_revision=run['head_sha'],run_id=str(run['id']),run_attempt='1')
    write(current/'execution.json',execution)
    member=generations.Generation.__new__(generations.Generation)
    member.context=ctx;member.generation=2;member.revision=run['head_sha'];member.run=run
    member.runner_sha=checkpoint.source_hash(run['head_sha'])
    member.paths={'cache':tmp_path/'continued-cache'}
    selected_row={**row,'job_id':12345,'job_name':'rohwer-checkpoint-continuation-0',
                  'artifact_name':'rohwer-checkpoint-continuation-BIOMD0000000038-partition-0-attempt-1'}
    member.selection={'selected':[selected_row]}
    job={'id':12345,'name':selected_row['job_name'],'run_id':run['id'],'run_attempt':1,'head_sha':run['head_sha'],
         'status':'completed','conclusion':'failure','started_at':'2026-11-26T00:00:00Z','completed_at':'2026-11-26T06:00:00Z'}
    member.jobs={'jobs':[job]}
    target=member.paths['cache']/str(run['id'])/'attempt-1/artifact-999';target.mkdir(parents=True)
    shutil.copytree(current,target/'evidence')
    if change=='array':
        path=next((target/'evidence'/row['branches'][0]['record_id']).glob('*.npz'))
        with path.open('ab') as stream:stream.write(b'tampered')
    elif change=='lineage':(target/'evidence/generations/2/parent-execution.json').write_text('{}')
    elif change=='source':
        path=target/'evidence/execution.json';value=read(path);value['producer_revision']='b'*40;write(path,value)
    archive=target/'download.zip'
    with zipfile.ZipFile(archive,'w') as stream:
        for path in (target/'evidence').rglob('*'):
            if path.is_file():stream.write(path,path.relative_to(target/'evidence'))
    artifact={'id':999,'name':selected_row['artifact_name'],'expired':False,
              'workflow_run':{'id':run['id'],'head_sha':run['head_sha']},'created_at':'2026-11-26T05:59:00Z',
              'digest':'sha256:'+generations.digest(archive),'size_in_bytes':archive.stat().st_size}
    member.artifacts={'artifacts':[artifact]}
    # Synthetic single-partition transport test. Actual all-32 ancestry and
    # complete selection are exercised above; every other branch stays pending.
    route=SimpleNamespace(validate_original=lambda *a:None,preserve=lambda *a:{'synthetic_fixture':True},
        for_index=lambda i:member if i==0 else None,assert_unchanged=lambda:None)
    result=full.verify_stage('diagnostics',paths,context,plan,{},output,store,diagnostic_generations=route)
    assert len(store)==11674 and bool(result['verification_errors'])==(change is not None)
    assert len(result['pending_partitions'])==31
    if change is None:
        bid=row['branches'][0]['record_id'];assert store[bid]['verified_arrays']==4
        assert store[bid]['run_id']==run['id'] and set(store[bid]['windows'])==set(full.LABELS)
        assert result['partitions'][0]['checkpoint_generation']==2
    else:assert not any(b['complete_diagnostic'] for b in store.index.values())
