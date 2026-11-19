"""Authenticated transport and real short-state restoration, not biology results."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import stat
import warnings
import zipfile

import numpy as np
import pytest

pytest.importorskip('mpmath')
from grn_memory import marhl_cloud as cloud
from grn_memory import marhl_precision as work

REVISION = 'a'*40
TIMES = np.array([0., .00999, .01001, .01999, .02001, .03])
TRAINS = [{'start': .01, 'stop': .02, 'interval': .01, 'include_start': True,
           'include_stop': False, 'values': {'CaM': .45}}]
SPEC = {'reset_trains': TRAINS, 'stop': .03, 'integration_settings': {}}

def short_problem(plan, inventory, index):
    return work.fingerprint(SPEC), list(work.REQUESTS)[index % 4], deepcopy(SPEC), TIMES.copy()

@pytest.fixture(scope='module')
def seed(tmp_path_factory):
    root = tmp_path_factory.mktemp('marhl-cloud-real-state')
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(work, 'problem', short_problem)
        for status, budget in [('partial', 1e-12), ('complete', 60.)]:
            report = work.run_task(cloud.PLAN, cloud.INVENTORY, 2, root/status, max_seconds=budget)
            assert report['status'] == ('checkpointed' if status == 'partial' else 'completed'), report
    return root

class FakeGitHub:
    repository = 'm9h/GRN_ODE'
    def __init__(self, archive):
        self.archive = archive
        self.run = {'id': 100, 'path': cloud.WORKFLOW, 'head_sha': REVISION, 'run_attempt': 1, 'status': 'completed'}
        self.job = {'id': 200, 'name': cloud.job_name(2), 'run_id': 100, 'status': 'completed',
                    'conclusion': 'failure', 'started_at': '2026-11-19T00:00:00Z'}
        self.artifact = {'id': 300, 'name': cloud.artifact_name(2, 1), 'expired': False,
                         'workflow_run': {'id': 100, 'head_sha': REVISION},
                         'created_at': '2026-11-19T00:01:00Z'}
        self.extra_jobs, self.extra_artifacts = [], []
        self.refresh()
    def refresh(self):
        self.artifact.update(size_in_bytes=self.archive.stat().st_size, digest='sha256:'+cloud.digest(self.archive))
    def api(self, endpoint):
        assert endpoint in ('actions/runs/100', 'actions/runs/101')
        return deepcopy(self.run if endpoint.endswith('/100') else {**self.run, 'id': 101, 'status': 'in_progress'})
    def rows(self, endpoint, field):
        if endpoint == 'actions/runs/100/attempts/1/jobs' and field == 'jobs':
            return deepcopy([self.job]+self.extra_jobs)
        if endpoint == 'actions/runs/101/attempts/1/jobs' and field == 'jobs':
            return [{**deepcopy(self.job), 'id': 201, 'run_id': 101, 'status': 'in_progress', 'conclusion': None}]
        assert endpoint == 'actions/runs/100/artifacts' and field == 'artifacts'
        return deepcopy([self.artifact]+self.extra_artifacts)
    def download(self, artifact_id, output):
        assert artifact_id == self.artifact['id']
        shutil.copyfile(self.archive, output)

def provenance():
    return {'source_revision': REVISION, 'file_sha256': cloud.source_files(), 'implementation_files_differing_from_revision': []}

@pytest.fixture
def parent(seed, tmp_path, monkeypatch):
    monkeypatch.setattr(work, 'problem', short_problem)
    payload = tmp_path/'parent'
    shutil.copytree(seed/'partial', payload/'evidence')
    report = work.read(payload/'evidence/report.json')
    execution = {'schema': 1, 'repository': 'm9h/GRN_ODE', 'run_id': 100, 'run_attempt': 1,
                 'job_id': 200, 'head_sha': REVISION, 'workflow_path': cloud.WORKFLOW,
                 'task_index': 2, 'batch': 0, 'task_count': 1520, 'plan_sha256': cloud.digest(cloud.PLAN),
                 'inventory_sha256': work.INVENTORY_SHA256, 'evidence_directory': 'evidence',
                 'source_provenance': provenance(), 'status': report['status'], 'finished_at': '2026-11-19T00:01:00Z'}
    cloud.write_json(payload/'execution.json', execution)
    archive = tmp_path/'parent.zip'
    def repack():
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for p in payload.rglob('*'):
                if p.is_file() and str(p.relative_to(payload)) in cloud.ALLOWED:
                    z.write(p, str(p.relative_to(payload)))
    repack()
    github = FakeGitHub(archive)
    return github, payload, repack

def test_every_original_task_is_selected_exactly_once():
    plan, _ = work.check_plan(cloud.PLAN, cloud.INVENTORY)
    all_tasks = [i for batch in range(6) for i in cloud.select_tasks(plan, batch)]
    assert all_tasks == list(range(1520))
    assert cloud.select_tasks(plan, 0, '[3,1]', 100) == [1, 3]

@pytest.mark.parametrize('batch,requested,parent_run', [(-1,'',None),(6,'',None),(True,'',None),
    (0,'[]',100),(0,'[0,0]',100),(0,'[256]',100),(0,'[true]',100),(0,'[1.0]',100),
    (0,'[0]',None),(0,'{}',100),(0,'',-1),(0,'',True)])
def test_invalid_or_fresh_subset_selection_is_rejected(batch, requested, parent_run):
    plan, _ = work.check_plan(cloud.PLAN, cloud.INVENTORY)
    with pytest.raises(ValueError):
        cloud.select_tasks(plan, batch, requested, parent_run)

def test_restore_verifies_real_state_and_keeps_parent_bytes(parent, tmp_path, monkeypatch):
    github, payload, _ = parent
    original = {str(p.relative_to(payload)): cloud.digest(p) for p in payload.rglob('*') if p.is_file()}
    original_zip = cloud.digest(github.archive)
    def forbidden(*args, **kwargs):
        pytest.fail('Restoration must not integrate')
    monkeypatch.setattr(work.marhl_checkpoints, 'trajectory', forbidden)
    monkeypatch.setattr(work.taylor_reference, 'taylor_trajectory', forbidden)
    target = tmp_path/'restored'
    result = cloud.restore(github, 100, 2, REVISION, target)
    assert result['validation']['checkpoint']['state_validated_in_matching_runtime']
    assert result['validation']['checkpoint']['completed'] is False
    assert result['validation']['checkpoint']['saved_samples'] == 2
    assert result['validation']['complete_array_verified'] is False
    assert result['numerical_integrations_performed'] == 0
    assert cloud.digest(target/'checkpoint.npz') == original['evidence/checkpoint.npz']
    assert cloud.digest(target/'report.json') == original['evidence/report.json']
    assert cloud.digest(github.archive) == original_zip
    assert original == {str(p.relative_to(payload)): cloud.digest(p) for p in payload.rglob('*') if p.is_file()}
    assert cloud.read(target/'restore-provenance.json')['history'] == [result]

@pytest.mark.parametrize('field', ['run_id','workflow','head','job_id','job_active','duplicate_job',
    'artifact_run','artifact_head','artifact_attempt','expired','predates_job','size','digest','duplicate_artifact'])
def test_mismatched_github_identities_never_publish(parent, tmp_path, field):
    github, _, _ = parent
    if field == 'run_id': github.run['id'] = 999
    elif field == 'workflow': github.run['path'] = '.github/workflows/other.yml'
    elif field == 'head': github.run['head_sha'] = 'b'*40
    elif field == 'job_id': github.job['run_id'] = 999
    elif field == 'job_active': github.job['status'] = 'in_progress'
    elif field == 'duplicate_job': github.extra_jobs = [deepcopy(github.job)]
    elif field == 'artifact_run': github.artifact['workflow_run']['id'] = 999
    elif field == 'artifact_head': github.artifact['workflow_run']['head_sha'] = 'b'*40
    elif field == 'artifact_attempt': github.artifact['name'] = cloud.artifact_name(2, 2)
    elif field == 'expired': github.artifact['expired'] = True
    elif field == 'predates_job': github.artifact['created_at'] = '2026-11-18T00:00:00Z'
    elif field == 'size': github.artifact['size_in_bytes'] += 1
    elif field == 'digest': github.artifact['digest'] = 'sha256:'+'0'*64
    elif field == 'duplicate_artifact': github.extra_artifacts = [deepcopy(github.artifact)]
    target = tmp_path/'rejected'
    with pytest.raises((ValueError, KeyError)):
        cloud.restore(github, 100, 2, REVISION, target)
    assert not target.exists()

@pytest.mark.parametrize('field', ['job_id','task_index','batch','plan_sha256','source_provenance','status'])
def test_mismatched_execution_envelopes_are_rejected(parent, tmp_path, field):
    github, payload, repack = parent
    execution = cloud.read(payload/'execution.json')
    execution[field] = 999 if field in ('job_id','task_index','batch') else 'changed'
    cloud.write_json(payload/'execution.json', execution); repack(); github.refresh()
    with pytest.raises(ValueError):
        cloud.restore(github, 100, 2, REVISION, tmp_path/'rejected')
    assert not (tmp_path/'rejected').exists()

@pytest.mark.parametrize('field', ['runtime','branch','source','checkpoint_bytes','checkpoint_missing','checkpoint_metadata'])
def test_invalid_numerical_state_is_rejected_even_with_valid_archive(parent, tmp_path, field):
    github, payload, repack = parent
    path = payload/'evidence/report.json';report = cloud.read(path)
    checkpoint = payload/'evidence/checkpoint.npz'
    if field == 'runtime': report['identity']['runtime']['python'] = 'different'
    elif field == 'branch': report['identity']['branch_id'] = '0'*64
    elif field == 'source': report['identity']['sources']['grn_memory/marhl_mpmath.py'] = '0'*64
    elif field == 'checkpoint_bytes': checkpoint.write_bytes(b'corrupt')
    elif field == 'checkpoint_missing': checkpoint.unlink()
    elif field == 'checkpoint_metadata':
        with np.load(checkpoint, allow_pickle=False) as z:
            metadata, observations = json.loads(str(z['metadata'])), z['observations'].copy()
        metadata['identity']['precision'] = 192
        metadata['identity_sha256'] = work.fingerprint(metadata['identity'])
        metadata.pop('payload_sha256');metadata['payload_sha256'] = work.fingerprint(metadata)
        np.savez_compressed(checkpoint, metadata=np.asarray(json.dumps(metadata)), observations=observations)
        report['checkpoint_sha256'] = cloud.digest(checkpoint)
    report['fingerprint'] = work.fingerprint(report['identity'])
    cloud.write_json(path, report); repack(); github.refresh()
    with pytest.raises((ValueError, OSError)):
        cloud.restore(github, 100, 2, REVISION, tmp_path/'rejected')
    assert not (tmp_path/'rejected').exists()

@pytest.mark.parametrize('kind', ['traversal','absolute','unexpected','duplicate','symlink','expanded_size'])
def test_unsafe_archives_are_rejected_before_publication(parent, tmp_path, monkeypatch, kind):
    github, _, _ = parent
    if kind == 'expanded_size':
        monkeypatch.setattr(cloud, 'MAX_ARCHIVE_BYTES', github.artifact['size_in_bytes']+1)
    else:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(github.archive, 'a') as z:
                if kind == 'symlink':
                    info = zipfile.ZipInfo('evidence/trajectory.npz'); info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    z.writestr(info, '/tmp/elsewhere')
                else:
                    name = {'traversal':'../escape','absolute':'/tmp/escape','unexpected':'evidence/object.pkl',
                            'duplicate':'execution.json'}[kind]
                    z.writestr(name, 'bad')
        github.refresh()
    with pytest.raises(ValueError):
        cloud.restore(github, 100, 2, REVISION, tmp_path/'rejected')
    assert not (tmp_path/'rejected').exists() and not (tmp_path/'escape').exists()

def test_completed_parent_arrays_are_revalidated(seed, parent, tmp_path):
    github, payload, repack = parent
    for name in ('report.json','checkpoint.npz','trajectory.npz'):
        shutil.copyfile(seed/'complete'/name, payload/'evidence'/name)
    execution = cloud.read(payload/'execution.json');execution['status'] = 'completed'
    cloud.write_json(payload/'execution.json', execution);repack();github.refresh()
    result = cloud.restore(github, 100, 2, REVISION, tmp_path/'restored')
    assert result['validation']['complete_array_verified'] is True
    assert result['validation']['checkpoint']['completed'] is True

def test_interrupted_wrapper_accepts_newer_valid_checkpoint_but_keeps_orphan_unclaimed(parent, tmp_path):
    github, payload, repack = parent
    report = cloud.read(payload/'evidence/report.json');report['status']='running';report['checkpoint_sha256']='stale'
    cloud.write_json(payload/'evidence/report.json', report)
    execution=cloud.read(payload/'execution.json');execution.pop('finished_at');execution['status']='running'
    cloud.write_json(payload/'execution.json', execution)
    (payload/'evidence/trajectory.npz').write_bytes(b'unclaimed interrupted output')
    repack();github.refresh()
    result = cloud.restore(github, 100, 2, REVISION, tmp_path/'restored')
    assert result['validation']['complete_array_verified'] is False
    assert result['validation']['unclaimed_orphan_trajectory'] is True

def test_cloud_continuation_preserves_prefix_and_matches_uninterrupted(seed, parent, tmp_path, monkeypatch):
    github, payload, _ = parent
    monkeypatch.setattr(cloud, 'verify_sources', lambda revision: provenance())
    result = cloud.execute(github, 101, 1, REVISION, 0, 2, tmp_path/'child', parent_run=100)
    assert result['status'] == 'completed'
    report=cloud.read(tmp_path/'child/evidence/report.json')
    assert len(report['attempts']) == 2 and report['attempts'][1]['resume'] is True
    with np.load(tmp_path/'child/evidence/trajectory.npz',allow_pickle=False) as z: values=z['values'].copy()
    with np.load(seed/'complete/trajectory.npz',allow_pickle=False) as z: expected=z['values'].copy()
    with np.load(payload/'evidence/checkpoint.npz',allow_pickle=False) as z: prefix=z['observations'].copy()
    assert np.array_equal(values,expected) and np.array_equal(values[:len(prefix)],prefix)
    assert cloud.read(tmp_path/'child/execution.json')['job_id'] == 201

def test_failed_restoration_never_starts_new_numerics(parent, tmp_path, monkeypatch):
    github, _, _ = parent
    github.artifact['digest']='sha256:'+'0'*64
    monkeypatch.setattr(cloud, 'verify_sources', lambda revision: provenance())
    monkeypatch.setattr(work, 'run_task', lambda *a,**k: pytest.fail('No fresh run after a failed restore'))
    with pytest.raises(ValueError):
        cloud.execute(github, 101, 1, REVISION, 0, 2, tmp_path/'child', parent_run=100)
    assert cloud.read(tmp_path/'child/execution.json')['status']=='restore_failed'
    assert not (tmp_path/'child/evidence').exists()

def test_source_revision_and_every_producer_file_are_checked(monkeypatch):
    calls=[]
    def git(command, **kwargs):
        calls.append(command)
        if command[1]=='rev-parse':return REVISION+'\n'
        name=command[2].split(':',1)[1]
        return (cloud.ROOT.parent/name).read_bytes()
    monkeypatch.setattr(cloud.subprocess,'check_output',git)
    assert cloud.verify_sources(REVISION)==provenance()
    assert len(calls)==len(cloud.source_files())+1
    def dirty(command,**kwargs):
        return REVISION+'\n' if command[1]=='rev-parse' else b'changed'
    monkeypatch.setattr(cloud.subprocess,'check_output',dirty)
    with pytest.raises(ValueError,match='Uncommitted'):
        cloud.verify_sources(REVISION)

@pytest.mark.parametrize('index',[0,1,2,3])
def test_real_checkpoint_context_matches_both_adapters_and_precisions(tmp_path,monkeypatch,index):
    if index < 2:pytest.importorskip('heyoka')
    monkeypatch.setattr(work,'problem',short_problem)
    output=tmp_path/'real'
    report=work.run_task(cloud.PLAN,cloud.INVENTORY,index,output,max_seconds=1e-12)
    assert report['status']=='checkpointed',report
    plan,inventory=work.check_plan(cloud.PLAN,cloud.INVENTORY)
    result=cloud.validate_evidence(output,plan,inventory,index)
    assert result['checkpoint']['state_validated_in_matching_runtime']
    assert result['checkpoint']['saved_samples']==2
    assert result['checkpoint']['completed'] is False
    final=work.run_task(cloud.PLAN,cloud.INVENTORY,index,output,resume=True,max_seconds=60.)
    assert final['status']=='completed',final
    assert cloud.validate_evidence(output,plan,inventory,index)['complete_array_verified']
