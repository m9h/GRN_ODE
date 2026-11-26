"""Verify sixteen exact original ZIPs and reproduce all 58 recorded Tyson cases."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import audit_breaking_shards as auditor
from scripts.audit_breaking_continuations import validate_plan

MANIFEST_SHA = 'c735ee08e45c7c51832e74a9651f5b2a436cc92f2c9561023eef7d2158f97459'
EXPECTED_SHA = 'b95f48a1f8dadc122bd64f91cb7aea6ad1fe2a7f6b27288cb37be5823fa124f0'

def require(condition, message):
    if not condition:
        raise ValueError(message)

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def read(path):
    return json.loads(path.read_text())

def normalized(result, directories):
    result = json.loads(json.dumps(result))
    for row, directory in zip(result['partitions'], directories, strict=True):
        row['directory'] = f'partition-{read(directory / "shard.json")["shard_index"]:02d}'
    return result

def reproduce(assets, output):
    require(not output.exists(), 'Use a fresh reproduction output directory')
    require(digest(assets / 'manifest.json') == MANIFEST_SHA, 'Pinned manifest differs')
    require(digest(assets / 'expected-audit.json') == EXPECTED_SHA, 'Pinned expected audit differs')
    manifest = read(assets / 'manifest.json')
    require(digest(assets / 'selection.json') == manifest['full_selection_sha256'], 'Full selection differs')
    selections = validate_plan(read(assets / 'selection.json'))
    require([r['shard_index'] for r in manifest['original_archives']] == list(range(16)),
            'All sixteen original partitions are required')
    output.mkdir(parents=True)
    directories, verified = [], []
    for row, selection in zip(manifest['original_archives'], selections, strict=True):
        require(all(row[k] == selection[k] for k in selection), 'Actual run/job/source binding differs')
        require(Path(row['file']).name == row['file'], 'Unsafe archive filename')
        archive = assets / row['file']
        require(archive.is_file() and not archive.is_symlink()
                and archive.stat().st_size == row['archive_bytes']
                and 'sha256:' + digest(archive) == row['archive_sha256'], 'Original ZIP bytes differ')
        directory = output / f'partition-{row["shard_index"]:02d}'
        directory.mkdir()
        names, hashes = set(), {}
        with zipfile.ZipFile(archive) as stream:
            for member in stream.infolist():
                name = member.filename.rstrip('/') if member.is_dir() else member.filename
                path = PurePosixPath(name)
                require(name and not path.is_absolute() and '..' not in path.parts and str(path) == name
                    and name not in names and '\\' not in name
                    and not stat.S_ISLNK(member.external_attr >> 16), 'Unsafe or duplicate ZIP member')
                names.add(name)
                if member.is_dir():
                    continue
                target = directory / path
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as destination:
                    destination.write(stream.read(member))
                hashes[name] = digest(target)
        require(hashes == row['files_sha256'], 'Original payload inventory differs')
        shard = read(directory / 'shard.json')
        require(shard['shard_index'] == row['shard_index']
                and shard['git_revision'] == row['producer_revision'], 'Embedded source identity differs')
        directories.append(directory)
        verified.append({'partition': row['shard_index'], 'artifact_id': row['artifact_id'],
                         'original_zip_sha256': row['archive_sha256'], 'verified_files': len(hashes)})
    result = auditor.audit(directories, 5)
    require(normalized(result, directories) == read(assets / 'expected-audit.json'),
            'Full recorded scientific audit does not reproduce')
    (output / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
    proof = {'manifest_sha256': MANIFEST_SHA, 'expected_audit_sha256': EXPECTED_SHA,
             'complete_case_coverage': result['complete_case_coverage'], 'cases': result['cases'],
             'passed_cases': result['passed_cases'], 'partitions_verified': verified,
             'branch_records_across_partitions': result['branch_records_across_partitions'],
             'unresolved_conditional_decisions': result['unresolved_conditional_decisions'],
             'all_numerical_validations_passed': result['all_numerical_validations_passed'],
             'normalization': 'Only the sixteen extraction directory paths are normalized.',
             'raw_full_trajectory_arrays_available': False, 'numerical_integrations_performed': 0}
    (output / 'reproduction-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    return proof

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reproduce(args.assets, args.output), indent=2))
