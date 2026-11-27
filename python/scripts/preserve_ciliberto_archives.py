"""Cloud transport for the pinned full Ciliberto archive inventory; no integration."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import archive_release_chunks as transport

INPUTS = ROOT / 'results/catalog-breaking-ciliberto-archive-preservation-20261126'
PLAN_SHA = '95709d654abdce1fcea4610b9f92746e4de309175663f6ca310aa2f12097a924'
PRIOR_PLAN_SHA = '60f3c1f1e7e40aae487fbd9b6377c35d9675aa6726b24328045cc26d202a54b2'


def validate_capture_ancestry(plan):
    """Newly available archives cannot replace or omit earlier identities."""
    reference = plan['parent_capture']
    transport.require(reference == {
        'source_revision': 'b19f222cb6a83f4f4f07ec4b639adc0359b7cbfd',
        'plan_file': 'prior-plan.json', 'plan_sha256': PRIOR_PLAN_SHA,
        'archive_count': 177, 'archive_bytes': 434442559593}, 'Prior archive capture identity differs')
    path = INPUTS / 'prior-plan.json'
    transport.require(transport.digest(path) == PRIOR_PLAN_SHA, 'Prior archive plan changed')
    prior = transport.read(path)
    for key in ('source_run', 'source_selection_sha256', 'required_partitions',
                'required_later_control_branches', 'required_full_case_branches', 'required_cases'):
        transport.require(plan[key] == prior[key], 'Original scientific selection changed')
    transport.require(len(plan['selected']) == len(prior['selected']) == 256, 'All original partitions remain required')
    for old, current in zip(prior['selected'], plan['selected'], strict=True):
        for key in ('index', 'job_id', 'release_tag'):
            transport.require(current[key] == old[key], 'Original archive route changed')
        if old['artifact'] is not None:
            transport.require(current['artifact'] is not None, 'Previously captured archive omitted')
            for key in ('id', 'name', 'size_in_bytes', 'digest', 'workflow_run', 'created_at'):
                transport.require(current['artifact'][key] == old['artifact'][key],
                                  'Previously captured archive identity changed')


def load_plan():
    transport.require(transport.digest(INPUTS / 'plan.json') == PLAN_SHA, 'Pinned archive plan changed')
    plan = transport.read(INPUTS / 'plan.json')
    transport.require(plan['repository'] == transport.REPOSITORY
        and [r['index'] for r in plan['selected']] == list(range(256))
        and plan['required_later_control_branches'] == 6859
        and plan['required_full_case_branches'] == 7334 and plan['required_cases'] == 74,
        'The complete original scientific scope is required')
    validate_capture_ancestry(plan)
    return plan


def validate():
    from scripts import audit_ciliberto_full_cases as full
    plan = load_plan()
    context, first_plan = full.load_context()
    scope = full.scope(context, first_plan)
    for name, sha in plan['api_sha256'].items():
        transport.require(transport.digest(INPUTS / 'api' / (name + '.json')) == sha,
                          'Pinned producer API snapshot changed')
    selection_path = INPUTS / 'selection.json'
    transport.require(transport.digest(selection_path) == plan['source_selection_sha256'],
                      'Pinned full source selection changed')
    run, jobs, artifacts = (transport.read(INPUTS / 'api' / (k + '.json'))
                             for k in ('run', 'jobs', 'artifacts'))
    selection = full.later.bind_selection(context[0], run, jobs)
    transport.require(selection == transport.read(selection_path), 'Full source selection differs')
    available = artifacts['artifacts']
    transport.require(artifacts['total_count'] == len(available) == plan['archive_count']
                      and len({a['id'] for a in available}) == len(available), 'Partial artifact inventory')
    for selected, row in zip(selection['selected'], plan['selected'], strict=True):
        transport.require(row['index'] == selected['index'] and row['job_id'] == selected['job_id']
            and row['release_tag'] == f'kinetics-ciliberto-archives-20261126-g{row["index"]//32:02d}',
            'Archive partition or destination differs')
        matches = [a for a in available if a['name'] == selected['artifact_name']]
        transport.require(len(matches) <= 1 and row['artifact'] == (matches[0] if matches else None),
                          'Original artifact inventory differs')
        if matches:
            job = next(j for j in jobs['jobs'] if j['id'] == row['job_id'])
            full.later.validate_artifact(selected, run, job, matches[0])
    transport.require(sum(a['size_in_bytes'] for a in available) == plan['archive_bytes'],
                      'Total original archive size differs')
    return {'plan_sha256': PLAN_SHA, 'archives': len(available), 'bytes': plan['archive_bytes'],
            'full_scientific_partitions': 256, 'full_scientific_branches': len(scope['branches']),
            'numerical_integrations_performed': 0}


def selected_rows(partitions):
    plan = load_plan()
    transport.require(isinstance(partitions, list) and partitions
        and all(type(i) is int and 0 <= i < 256 for i in partitions)
        and len(set(partitions)) == len(partitions), 'Choose unique archive indices in the full inventory')
    rows = [plan['selected'][i] for i in sorted(partitions)]
    transport.require(all(r['artifact'] is not None for r in rows), 'An archive is not available in this snapshot')
    return rows


def prepare_releases(rows, source_sha, notes):
    transport.require(len(source_sha) == 40 and all(c in '0123456789abcdef' for c in source_sha),
                      'Pin the courier source revision')
    for tag in sorted({r['release_tag'] for r in rows}):
        result = subprocess.run(['gh', 'api', f'repos/{transport.REPOSITORY}/releases/tags/{tag}'],
                                capture_output=True, text=True)
        if result.returncode:
            transport.require('HTTP 404' in result.stderr, 'Cannot determine whether the release already exists')
            subprocess.run(['gh', 'release', 'create', tag, '--repo', transport.REPOSITORY,
                '--target', source_sha, '--title', tag, '--notes-file', str(notes)], check=True)
        else:
            release = json.loads(result.stdout)
            transport.require(not release['draft'] and release['tag_name'] == tag,
                              'Existing archive release identity differs')


def preserve(index, output):
    row = selected_rows([index])[0]
    transport.require(not output.exists(), 'Use a fresh courier output directory')
    output.mkdir(parents=True)
    api = transport.GitHub()
    artifact = row['artifact']
    fresh = api.json(f'repos/{transport.REPOSITORY}/actions/artifacts/{artifact["id"]}')
    transport.require(transport.artifact_identity(fresh) == transport.artifact_identity(artifact)
        and fresh['expired'] is False and fresh['created_at'] == artifact['created_at'],
        'Current original artifact identity differs or has expired')
    transport.write_new(output / 'original-artifact-api.json', fresh)
    archive = output / 'original.zip'
    api.download(f'repos/{transport.REPOSITORY}/actions/artifacts/{artifact["id"]}/zip', archive)
    receipt = transport.publish(archive, artifact, row['release_tag'], output / 'publication', api=api)
    transport.write_new(output / 'preservation-proof.json', {'plan_sha256': PLAN_SHA,
        'source_run': load_plan()['source_run'], 'partition': index, 'original_job_id': row['job_id'],
        'courier_revision': os.environ.get('GITHUB_SHA'), 'receipt': receipt,
        'numerical_integrations_performed': 0, 'scientific_recovery_claimed': False})
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['check', 'matrix', 'publish'])
    parser.add_argument('--partitions', default='[0]')
    parser.add_argument('--create-releases', action='store_true')
    parser.add_argument('--index', type=int)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.operation == 'check':
        print(json.dumps(validate()))
    elif args.operation == 'matrix':
        rows = selected_rows(json.loads(args.partitions))
        if args.create_releases:
            prepare_releases(rows, os.environ['GITHUB_SHA'], INPUTS / 'RELEASE_NOTES.md')
        matrix = {'include': [{'index': r['index']} for r in rows]}
        print(json.dumps(matrix))
        if 'GITHUB_OUTPUT' in os.environ:
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                stream.write('matrix=' + json.dumps(matrix, separators=(',', ':')) + '\n')
    else:
        transport.require(args.index is not None and args.output is not None, 'Specify partition and fresh output')
        print(json.dumps(preserve(args.index, args.output)))
