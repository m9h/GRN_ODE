"""Reaudit the full retained Vilar selection with each pinned source version.

No integration or network access occurs. Legacy and segment-checkpoint reports
remain separate provenance groups; neither source identity check is weakened.
"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
MODERN = HERE.parents[1]
MANIFEST_SHA = '7a393e4e105da539d6d60688f2e6974c78f1df5c8ed14752baf9e5280d303090'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text())


def manifest():
    require(digest(HERE / 'manifest.json') == MANIFEST_SHA, 'Pinned complete manifest differs')
    data = read(HERE / 'manifest.json')
    require([r['index'] for r in data['selected']] == list(range(17))
            and len(data['original_archives']) == 27
            and len({r['artifact_id'] for r in data['original_archives']}) == 27,
            'Complete selected and ancestral archive inventories are required')
    return data


def check_source(source, group, data):
    for name, sha in data['worker_source_sha256'][group].items():
        require(digest(source / name) == sha, 'Pinned audit source differs: ' + name)


def worker(index, source, archives, output):
    data = manifest()
    row = data['selected'][index]
    check_source(source, row['source_group'], data)
    # Separate processes prevent imports from one source version being reused by
    # the other. Each original auditor reconstructs its own complete model scope.
    sys.path.insert(0, str(source))
    from scripts.collect_taylor_runs import download_partition
    from grn_memory.taylor_checkpoints import signature
    import numpy as np

    api = HERE / 'api' / str(row['run_id'])
    for name, sha in data['api_sha256'][str(row['run_id'])].items():
        require(digest(api / name) == sha, 'Pinned producer API snapshot differs')
    run, jobs, artifacts = (read(api / (key + '.json')) for key in ('run', 'jobs', 'artifacts'))
    require(jobs['total_count'] == len(jobs['jobs']) and artifacts['total_count'] == len(artifacts['artifacts']),
            'Complete original API pagination is required')
    require(run['id'] == row['run_id'] and run['run_attempt'] == row['run_attempt']
            and run['head_sha'] == row['producer_revision'] and run['status'] == 'completed'
            and run['path'] == '.github/workflows/precision-checkpoints.yml', 'Original producer identity differs')
    job = next(j for j in jobs['jobs'] if j['id'] == row['job_id'])
    artifact = next(a for a in artifacts['artifacts'] if a['id'] == row['artifact_id'])
    require(job['run_id'] == run['id'] and job['run_attempt'] == run['run_attempt']
            and job['head_sha'] == run['head_sha'] and job['status'] == 'completed'
            and job['name'] == artifact['name'] == f'precision-model-35-partition-{index}',
            'Original job and artifact selection differs')
    require(datetime.fromisoformat(job['started_at']) <= datetime.fromisoformat(artifact['created_at'])
            <= datetime.fromisoformat(job['completed_at']), 'Artifact belongs to another execution')
    archive = archives / f'artifact-{artifact["id"]}.zip'
    require(archive.is_file() and not archive.is_symlink()
            and archive.stat().st_size == artifact['size_in_bytes']
            and 'sha256:' + digest(archive) == artifact['digest'] == row['archive_sha256'],
            'Original ZIP bytes differ')

    class OfflineArtifact:
        def download(self, artifact_id, destination):
            require(artifact_id == row['artifact_id'], 'Unexpected archive request')
            shutil.copyfile(archive, destination)

    output.mkdir(parents=True, exist_ok=False)
    checked = download_partition(OfflineArtifact(), artifact, job, run, 35, index, output)
    keys = ('index', 'artifact_id', 'archive_sha256', 'execution_sha256', 'report_sha256',
            'reported_status', 'complete_arrays_audited', 'diagnostic_status', 'public_evidence_sha256')
    require(all(checked[key] == row[key] for key in keys), 'Fresh partition verification differs')
    evidence = Path(checked['directory'])
    report = read(evidence / 'report.json')
    require(report['selection'] == row['selection'] and report['environment'] == row['environment']
            and {k: v for k, v in report['core'].items() if k != 'implementation_sha256'}
                == data['common_scientific_core'], 'Scientific protocol or environment differs')
    proof = {'index': index, 'artifact_id': artifact['id'], 'source_group': row['source_group'],
             'reported_status': checked['reported_status'], 'diagnostic_status': checked['diagnostic_status'],
             'complete_arrays': len(checked['completed_integrations']), 'archive_sha256': artifact['digest'],
             'full_array_audit_reproduced': checked['complete_arrays_audited']}
    if checked['complete_arrays_audited']:
        expected = HERE / row['expected_audit']
        require(digest(expected) == row['expected_audit_sha256'], 'Pinned numerical audit differs')
        require(read(Path(checked['audit'])) == read(expected), 'Full-array scientific audit does not reproduce')
    else:
        require(report['status'] == 'checkpointed' and not report['traces'], 'Incomplete work promoted')
        path = evidence / 'taylor128-checkpoint.npz'
        require(digest(path) == report['integrations']['taylor128']['checkpoint_sha256'], 'Checkpoint differs')
        with np.load(path, allow_pickle=False) as archive:
            require(set(archive.files) == {'metadata', 'observations'}, 'Checkpoint members differ')
            meta, observations = json.loads(str(archive['metadata'])), archive['observations'].copy()
        checksum = meta.pop('payload_sha256')
        require(signature(meta) == checksum and signature(meta['identity']) == meta['identity_sha256']
                and hashlib.sha256(observations.tobytes()).hexdigest() == meta['observations_sha256'],
                'Portable checkpoint checksums differ')
        proof.update(saved_samples=len(observations), checkpoint_sha256=digest(path),
                     native_mpfr_state_validation='Required in matching Linux runtime before resume')
    (output / 'partition-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    return proof


def reproduce(legacy, archives, output):
    data = manifest()
    require(not output.exists(), 'Use a fresh reproduction directory')
    check_source(legacy, 'legacy', data)
    check_source(MODERN, 'segment_checkpoints', data)
    require({p.name for p in archives.iterdir()} == {r['file'] for r in data['original_archives']},
            'Every original and ancestral ZIP must be supplied without substitutions')
    for row in data['original_archives']:
        path = archives / row['file']
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == row['bytes']
                and digest(path) == row['sha256'], 'Original or ancestral ZIP changed')
    output.mkdir(parents=True)
    proofs = []
    for row in data['selected']:
        source = legacy if row['source_group'] == 'legacy' else MODERN
        target = output / f'partition-{row["index"]:02d}'
        subprocess.run([sys.executable, '-B', str(Path(__file__)), '--worker-index', str(row['index']),
                        '--worker-source', str(source), '--archives', str(archives), '--output', str(target)],
                       check=True, stdout=subprocess.PIPE, text=True)
        proofs.append(read(target / 'partition-proof.json'))
    completed = [p for p in proofs if p['full_array_audit_reproduced']]
    incomplete = [p['index'] for p in proofs if not p['full_array_audit_reproduced']]
    require(len(completed) == 13 and sum(p['complete_arrays'] for p in proofs) == 39
            and incomplete == [8, 9, 11, 16], 'Complete scientific selection differs')
    proof = {'manifest_sha256': MANIFEST_SHA, 'original_archives_verified': 27,
             'original_zip_bytes': sum(r['bytes'] for r in data['original_archives']),
             'selected_partitions': 17, 'complete_selected_partitions': 13, 'verified_complete_arrays': 39,
             'incomplete_selected_indices': incomplete,
             'complete_partition_outcomes': dict(Counter(p['diagnostic_status'] for p in completed)),
             'partitions': proofs, 'case_recovery_claimed': False,
             'complete_original_failure_coverage': False, 'cross_version_same_trajectory_claimed': False,
             'numerical_integrations_performed': 0}
    (output / 'reproduction-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    return proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archives', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--legacy-python-root', type=Path)
    parser.add_argument('--worker-index', type=int)
    parser.add_argument('--worker-source', type=Path)
    args = parser.parse_args()
    if args.worker_index is not None:
        require(0 <= args.worker_index < 17 and args.worker_source is not None, 'Invalid worker selection')
        result = worker(args.worker_index, args.worker_source, args.archives, args.output)
    else:
        require(args.legacy_python_root is not None, 'Declare the pinned legacy Python source directory')
        result = reproduce(args.legacy_python_root, args.archives, args.output)
    print(json.dumps(result, indent=2))
