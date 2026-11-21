"""Package Ueda's preserved raw evidence and reproduce its preparation offline.

This is an incomplete-case evidence release. It performs no ODE integrations
and cannot claim a recovered case or a passing whole-model audit.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def safe_name(name):
    require(isinstance(name, str) and bool(name), 'Invalid archive path')
    path = PurePosixPath(name)
    require(not path.is_absolute() and '..' not in path.parts and str(path) == name and '\\' not in name,
            'Unsafe or noncanonical archive path')
    return path


def checked_file(path, entry):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size == entry['bytes']
            and digest(path) == entry['sha256'], 'Evidence size or checksum differs: '+str(path))


def create_archive(path, entries, sources):
    require(not path.exists(), 'Archive already exists')
    require(len({r['path'] for r in entries}) == len(entries), 'Duplicate archive member')
    with tarfile.open(path, 'w', format=tarfile.USTAR_FORMAT) as archive:
        for entry, source in zip(entries, sources, strict=True):
            safe_name(entry['path'])
            checked_file(source, entry)
            member = tarfile.TarInfo(entry['path'])
            member.size, member.mode, member.mtime = entry['bytes'], 0o644, 0
            with source.open('rb') as stream:
                archive.addfile(member, stream)
    return {'name': path.name, 'bytes': path.stat().st_size, 'sha256': digest(path), 'members': entries}


def extract_archive(path, asset, output):
    checked_file(path, asset)
    expected = {r['path']: r for r in asset['members']}
    require(len(expected) == len(asset['members']), 'Duplicate manifest member')
    for name in expected:
        parts = safe_name(name).parts
        require(len(parts) == 2 and parts[0] == asset['role'], 'Unexpected evidence prefix')
    with tarfile.open(path, 'r:') as archive:
        members = archive.getmembers()
        require(len(members) == len(expected) and {m.name for m in members} == set(expected),
                'Archive inventory differs')
        for member in members:
            entry = expected[member.name]
            require(member.isfile() and member.size == entry['bytes'], 'Unexpected archive member type or size')
            target = output/safe_name(member.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open('xb') as destination:
                shutil.copyfileobj(source, destination)
            checked_file(target, entry)


PREPARATION_OUTPUTS = ('preserved-audit.json', 'restoration-proof.json', 'continuation-plan.json')


def pack(evidence, assets):
    assets.mkdir(parents=True, exist_ok=False)
    preservation = read(HERE/'preservation-manifest.json')
    entries = sorted(preservation['files'], key=lambda r: r['path'])
    require({p.name for p in (evidence/'observed-source').iterdir()} == {r['path'] for r in entries},
            'Preserved snapshot inventory differs')
    manifest = {'schema_version': 1, 'purpose': __doc__, 'model_id': 'BIOMD0000000022',
        'preservation_manifest_sha256': digest(HERE/'preservation-manifest.json'),
        'original_report_sha256': digest(HERE/'report.json'),
        'preparation_script_sha256': digest(ROOT/'scripts/prepare_ueda_continuation.py'),
        'preparation_outputs_sha256': {n: digest(HERE/n) for n in PREPARATION_OUTPUTS},
        'snapshot_files': len(entries), 'snapshot_bytes': sum(r['bytes'] for r in entries),
        'numerical_integrations_performed': 0, 'case_recovery_claimed': False, 'assets': []}
    groups, group, size = [], [], 0
    for entry in entries:
        require(Path(entry['path']).name == entry['path'], 'Preserved filename is not flat')
        if group and size+entry['bytes'] > 1_000_000_000:
            groups.append(group)
            group, size = [], 0
        group.append(entry)
        size += entry['bytes']
    if group:
        groups.append(group)
    for index, group in enumerate(groups):
        members = [{'path': 'preserved/'+r['path'], 'bytes': r['bytes'], 'sha256': r['sha256']} for r in group]
        sources = [evidence/'observed-source'/r['path'] for r in group]
        asset = create_archive(assets/f'ueda-preserved-{index:02d}.tar', members, sources)
        manifest['assets'].append({'role': 'preserved', **asset})
        print(json.dumps({'packed': asset['name'], 'bytes': asset['bytes']}), flush=True)
    published = read(HERE/'published-import-manifest.json')
    asset = {'role': 'published_diagnostic', 'name': published['archive'],
             'bytes': published['archive_bytes'], 'sha256': published['archive_sha256']}
    checked_file(evidence/'downloads'/asset['name'], asset)
    shutil.copyfile(evidence/'downloads'/asset['name'], assets/asset['name'])
    checked_file(assets/asset['name'], asset)
    manifest['assets'].append(asset)
    write(assets/'release-manifest.json', manifest)
    print(json.dumps({'evidence_assets': len(manifest['assets']),
                      'bytes': sum(r['bytes'] for r in manifest['assets'])}), flush=True)


def verify_result(manifest, fresh):
    require(set(manifest['preparation_outputs_sha256']) == set(PREPARATION_OUTPUTS),
            'Preparation output inventory differs')
    for name in PREPARATION_OUTPUTS:
        expected = manifest['preparation_outputs_sha256'][name]
        require(digest(HERE/name) == expected, 'Pinned preparation evidence differs')
        require(digest(fresh/name) == expected, 'Fresh preparation does not reproduce exactly: '+name)


def reproduce(assets, output):
    from scripts.prepare_ueda_continuation import prepare

    manifest = read(HERE/'release-manifest.json')
    require(manifest['schema_version'] == 1 and manifest['model_id'] == 'BIOMD0000000022'
            and manifest['case_recovery_claimed'] is False and manifest['numerical_integrations_performed'] == 0,
            'Unexpected release scope or recovery claim')
    require(digest(assets/'release-manifest.json') == digest(HERE/'release-manifest.json'),
            'Downloaded manifest differs from pinned repository')
    require(manifest['preservation_manifest_sha256'] == digest(HERE/'preservation-manifest.json')
            and manifest['original_report_sha256'] == digest(HERE/'report.json')
            and manifest['preparation_script_sha256'] == digest(ROOT/'scripts/prepare_ueda_continuation.py'),
            'Original evidence or preparation code differs')
    require(len({a['name'] for a in manifest['assets']}) == len(manifest['assets']), 'Duplicate asset name')
    output.mkdir(parents=True, exist_ok=False)
    published = []
    for asset in manifest['assets']:
        require(Path(asset['name']).name == asset['name'], 'Invalid asset filename')
        source = assets/asset['name']
        checked_file(source, asset)
        if asset['role'] == 'preserved':
            extract_archive(source, asset, output)
        else:
            require(asset['role'] == 'published_diagnostic', 'Unexpected asset role')
            published.append(source)
        print(json.dumps({'verified_asset': asset['name']}), flush=True)
    require(len(published) == 1, 'Exactly one original published diagnostic archive is required')
    prepare(argparse.Namespace(snapshot=output/'preserved', manifest=HERE/'preservation-manifest.json',
        inputs=HERE, archive=published[0], release_manifest=HERE/'published-import-manifest.json',
        output=output/'preparation'))
    verify_result(manifest, output/'preparation')
    plan = read(output/'preparation/continuation-plan.json')
    audit = read(output/'preparation/preserved-audit.json')
    proof = {'fresh_preparation_reproduced_exactly': True, 'verified_evidence_assets': len(manifest['assets']),
        'manifest_sha256': digest(HERE/'release-manifest.json'), 'reproducer_sha256': digest(Path(__file__)),
        'preparation_script_sha256': manifest['preparation_script_sha256'],
        'preparation_outputs_sha256': {n: digest(output/'preparation'/n) for n in PREPARATION_OUTPUTS},
        'snapshot_files': manifest['snapshot_files'], 'verified_preserved_arrays': audit['verified_arrays'],
        'complete_preserved_branches': len(audit['complete_branch_ids']), 'published_imports': len(plan['imported_branch_ids']),
        'complete_distinct_branches_available': plan['expected_full_branches']-len(plan['selected_branch_ids']),
        'remaining_branches': len(plan['selected_branch_ids']), 'full_case_inventory': plan['expected_full_branches'],
        'selected_cases': plan['expected_selected_cases'], 'numerical_integrations_performed': 0,
        'case_recovery_claimed': False, 'full_model_coverage_claimed': False}
    write(output/'reproduction-verification.json', proof)
    print(json.dumps(proof), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('pack', 'reproduce'))
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.operation == 'pack':
        require(args.evidence is not None, 'Packing requires --evidence')
        pack(args.evidence, args.assets)
    else:
        require(args.output is not None, 'Reproduction requires --output')
        reproduce(args.assets, args.output)
