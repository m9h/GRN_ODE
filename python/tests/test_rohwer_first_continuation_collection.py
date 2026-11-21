"""Fixed-scope collection API contract; no integrations or network requests."""

from copy import deepcopy
import pytest

from scripts import collect_rohwer_first_continuation as c


def fixture():
    plan = c.read(c.continuation.INPUTS/'plan.json')
    run = {'id': 1234, 'run_attempt': 1, 'head_sha': 'a'*40,
           'event': 'workflow_dispatch', 'path': c.WORKFLOW}
    common = {'run_id': 1234, 'run_attempt': 1, 'head_sha': 'a'*40}
    jobs = [{'id': 999, 'name': 'validation', 'status': 'completed', 'conclusion': 'success', **common}]
    jobs += [{'id': 100+i, 'name': f'rohwer-first-continuation-{i}', 'status': 'queued',
              'conclusion': None, **common} for i in range(32)]
    return plan, run, {'total_count': 33, 'jobs': jobs}


def test_bind_all_750_original_branches_once():
    plan, run, jobs = fixture()
    selection = c.bind(plan, run, jobs, 'a'*40)
    branches = [b['record_id'] for p in selection['selected'] for b in p['branches']]
    assert len(branches) == len(set(branches)) == 750
    assert len(selection['selected']) == 32
    assert not selection['case_recovery_claimed'] and not selection['full_model_coverage_claimed']


@pytest.mark.parametrize('mutation', ['gate', 'missing', 'duplicate_name', 'duplicate_id', 'pages',
                                     'run_source', 'job_source', 'run_attempt', 'event', 'workflow'])
def test_reject_incomplete_or_misbound_collection(mutation):
    plan, run, jobs = fixture()
    if mutation == 'gate': jobs['jobs'][0]['conclusion'] = 'failure'
    elif mutation == 'missing': jobs['jobs'].pop(); jobs['total_count'] -= 1
    elif mutation == 'duplicate_name': jobs['jobs'][-1]['name'] = jobs['jobs'][-2]['name']
    elif mutation == 'duplicate_id': jobs['jobs'][-1]['id'] = jobs['jobs'][-2]['id']
    elif mutation == 'pages': jobs['total_count'] += 1
    elif mutation == 'run_source': run['head_sha'] = 'b'*40
    elif mutation == 'job_source': jobs['jobs'][1]['head_sha'] = 'b'*40
    elif mutation == 'run_attempt': run['run_attempt'] = 2
    elif mutation == 'event': run['event'] = 'push'
    else: run['path'] = '.github/workflows/different.yml'
    with pytest.raises(ValueError): c.bind(plan, run, jobs, 'a'*40)


def test_failed_job_output_retained_but_wrong_artifact_rejected():
    plan, run, jobs = fixture()
    row = c.bind(plan, run, jobs, 'a'*40)['selected'][0]
    job = jobs['jobs'][1]
    job.update(status='completed', conclusion='failure', started_at='2026-11-21T18:00:00Z',
               completed_at='2026-11-21T19:00:00Z')
    artifact = {'id': 42, 'name': row['artifact_name'], 'expired': False,
                'workflow_run': {'id': run['id'], 'head_sha': run['head_sha']},
                'created_at': '2026-11-21T18:59:00Z', 'digest': 'sha256:'+'0'*64, 'size_in_bytes': 1}
    c.validate_artifact(row, run, job, artifact)
    for mutation in ('identity', 'digest', 'expired', 'outside_job'):
        bad = deepcopy(artifact)
        if mutation == 'identity': bad['workflow_run']['id'] += 1
        elif mutation == 'digest': bad.pop('digest')
        elif mutation == 'expired': bad['expired'] = True
        else: bad['created_at'] = '2026-11-21T19:00:01Z'
        with pytest.raises(ValueError): c.validate_artifact(row, run, job, bad)


def test_pending_and_missing_jobs_do_not_shrink_full_scope(tmp_path, monkeypatch):
    plan, run, jobs = fixture()
    jobs['jobs'][1].update(status='completed', conclusion='failure')
    requirements = c.read(c.continuation.BINDINGS/'continuation-requirements.json')
    monkeypatch.setattr(c.continuation, 'check_bindings', lambda: (plan, requirements, None, None))
    snapshots = tmp_path/'snapshots'
    snapshots.mkdir()
    for name, value in [('run', run), ('jobs', jobs), ('artifacts', {'total_count': 0, 'artifacts': []})]:
        c.write(snapshots/(name+'.json'), value)
    selection = tmp_path/'selection.json'
    c.write(selection, c.bind(plan, run, jobs, 'a'*40))
    status = c.collect(selection, snapshots, tmp_path/'archives', tmp_path/'collection')
    assert status['fixed_branch_count'] == 750
    assert status['status'] == 'incomplete'
    assert status['pending_indices'] == list(range(1, 32))
    assert status['missing_artifacts'] == [{'index': 0, 'reason': 'no_artifact'}]
    assert not status['complete_selected_diagnostics'] and not status['collection_errors']
