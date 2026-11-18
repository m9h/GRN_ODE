"""Audit preserved Ueda arrays and select every branch still needing computation.

This preparation never integrates ODEs or edits the stopped worker's output.
Selection depends on missing evidence, never on whether a comparison passes.
The final unchanged case auditor still requires all 323 branches and four cases.
"""

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import require
from grn_memory.catalog_jax import source_hashes
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import comparison
from grn_memory.native_protocols import ResetTrain
from grn_memory.scipy_breaking_recovery import LABELS, prepare_inventory
from scripts.audit_scipy_breaking import PACKAGES, SOURCES, audit as audit_diagnostic, trajectory
from scripts.audit_scipy_breaking_cases import META_KEYS, check_outcome
from scripts import diagnose_scipy_breaking_controls as producer

RELEASE_SHA = '8044deaf4f75c30da35cbf8610a7d8422e9f3d54dd2e351be088dbaa3353a5d1'
MANIFEST_SHA = 'c3be7e92d5a8212222f53c4c9c9ccad7120afd3d4c8d884bc88f9363147af8be'
SOURCE_REVISION = '70a3afad61357e94873ff62a7300c099b4c7ae3e'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def select_remaining(inventory, preserved, imported):
    wanted = set(inventory['branches'])
    require(len(preserved) == len(set(preserved)) and len(imported) == len(set(imported)),
            'Duplicate preserved or imported branch')
    require(set(preserved) <= wanted and set(imported) <= wanted, 'Evidence outside original inventory')
    return sorted(wanted - set(preserved) - set(imported))


def extract_release(archive_path, manifest_path, destination):
    require(digest(archive_path) == RELEASE_SHA and digest(manifest_path) == MANIFEST_SHA,
            'Published release bytes differ')
    manifest = read(manifest_path)
    expected = manifest['member_sha256']
    require(manifest['archive_sha256'] == RELEASE_SHA, 'Release manifest archive differs')
    destination.mkdir()
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        require(len(members) == len(expected) == manifest['member_count']
                and {m.name for m in members} == set(expected), 'Archive member inventory differs')
        for member in members:
            path = Path(member.name)
            require(member.isfile() and len(path.parts) == 2
                    and path.parts[0] == 'catalog-breaking-scipy-ueda11', 'Unsafe archive member')
            data = archive.extractfile(member).read()
            require(hashlib.sha256(data).hexdigest() == expected[member.name], 'Release member digest differs')
            (destination / path.name).write_bytes(data)
    return manifest


def verify_snapshot(snapshot, manifest_path):
    manifest = read(manifest_path)
    entries = {r['path']: r for r in manifest['files']}
    require(len(entries) == len(manifest['files'])
            and set(entries) == {p.name for p in snapshot.iterdir()}, 'Snapshot file inventory differs')
    for name, entry in entries.items():
        require(Path(name).name == name, 'Unsafe snapshot member')
        path = snapshot / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == entry['bytes']
                and digest(path) == entry['sha256'], 'Snapshot member differs: ' + name)
    return manifest


def audit_preserved(snapshot, report, inventory, info, grid, imported):
    entries = {r['record_id']: r for r in report['branches']}
    require(len(entries) == len(report['branches']) and set(entries) <= set(inventory['branches']),
            'Original report selection differs')
    existing = {p.stem for p in snapshot.glob('*.json') if len(p.stem) == 64}
    require(existing <= set(inventory['branches']), 'Unexpected preserved branch record')
    rows, full, missing_arrays = [], [], []
    arrays = 0
    for bid in sorted(existing):
        path = snapshot / (bid + '.json')
        record = read(path)
        if bid in entries:
            require(digest(path) == entries[bid]['sha256'], 'Historical record hash differs')
        spec = inventory['branches'][bid]
        require(record['record_id'] == bid and record['specification'] == spec
                and record['fingerprint'] == report['fingerprint']
                and record['case_recovery_claimed'] is False, 'Preserved record identity differs')
        require(set(record['integrations']) <= set(LABELS)
                and set(record['traces']) == {k for k, v in record['integrations'].items() if v.get('completed') is True},
                'Preserved integration and trace inventories differ')
        if bid in imported:
            require(record.get('reused_from') == {'report_sha256': report['reused_report_sha256'],
                    'record_sha256': imported[bid]['sha256']}, 'Imported provenance differs')
        else:
            require('reused_from' not in record, 'Unexpected import provenance')
        times = grid[grid <= spec['stop']]
        trains = [ResetTrain(**t) for t in spec['reset_trains']]
        traces = {}
        for label, outcome in record['integrations'].items():
            require(outcome['request'] == report['requests'][label], 'Preserved request differs')
            if outcome.get('completed') is not True:
                require(outcome.get('completed') is False, 'Invalid completion flag')
                continue
            check_outcome(outcome, label, report['requests'][label], times, info['observables'], trains, info['sha256'])
            saved = record['traces'][label]
            require(saved['file'] == bid + '-' + label + '.npz', 'Preserved trajectory path differs')
            if not (snapshot / saved['file']).exists():
                missing_arrays.append(saved['file'])
                continue
            traces[label] = trajectory(snapshot, bid, label, saved, times, info['observables'])
            arrays += 1
        comparisons = {a + '_vs_' + b: comparison(traces[a], traces[b], **report['acceptance'])
                       for i, a in enumerate(LABELS) for b in LABELS[i+1:] if a in traces and b in traces}
        complete = len(traces) == 4
        if complete:
            status = 'confirmed' if all(c['passed'] for c in comparisons.values()) else 'mismatch'
            require(record['comparisons'] == comparisons and record['status'] == status
                    and bid in entries and entries[bid]['status'] == status,
                    'Historical comparisons do not reproduce')
            full.append(bid)
        rows.append({'record_id': bid, 'record_sha256': digest(path), 'complete': complete,
                     'arrays_verified': len(traces), 'comparisons': comparisons})
        if len(rows) % 20 == 0:
            print(json.dumps({'records_checked': len(rows), 'arrays_checked': arrays}), flush=True)
    referenced = {v['file'] for bid in existing for v in read(snapshot/(bid+'.json'))['traces'].values()}
    require({p.name for p in snapshot.glob('*.npz')} <= referenced, 'Unreferenced saved trajectory')
    return {'complete_branch_ids': full, 'branches': rows, 'verified_arrays': arrays,
            'missing_reported_branch_ids': sorted(set(entries)-existing), 'missing_arrays': sorted(missing_arrays)}


def prepare(args):
    require(not args.output.exists(), 'Use a fresh preparation directory')
    manifest = verify_snapshot(args.snapshot, args.manifest)
    report = read(args.snapshot / 'report.json')
    require(fingerprint({k: report[k] for k in META_KEYS}) == report['fingerprint'], 'Producer fingerprint differs')
    inventory, path, info, grid = prepare_inventory(args.inputs/'source-evidence.json',
        args.inputs/'original-case-plan.json', SOURCE_REVISION, args.inputs/'source-branches.jsonl.gz')
    require(read(args.inputs/'inventory.json') == inventory and fingerprint(inventory) == report['inventory_sha256']
            and inventory['expected_branches'] == report['expected_branches'] == 323
            and len(inventory['cases']) == len(report['selected_case_keys']) == 4
            and sorted(inventory['cases']) == report['selected_case_keys'], 'Full Ueda case scope differs')
    sources = source_hashes()
    sources.update({n: digest(ROOT/n) for n in (*SOURCES, *producer.EXTRA_SOURCES)})
    require(sources == report['implementation_sha256'], 'Numerical source differs')
    require({p: version(p) for p in PACKAGES} == report['versions'], 'Numerical package versions differ')
    require(report['model_sha256'] == info['sha256']
            and report['sample_grid_sha256'] == hashlib.sha256(grid.tobytes()).hexdigest(), 'Model or grid differs')
    args.output.mkdir()
    published = args.output/'published-diagnostic'
    extract_release(args.archive, args.release_manifest, published)
    reused = read(published/'report.json')
    require(digest(published/'report.json') == report['reused_report_sha256'], 'Original diagnostic report differs')
    reused_audit = audit_diagnostic(published)
    require(fingerprint(reused_audit) == report['reused_audit_sha256'], 'Original diagnostic audit differs')
    imported = {r['record_id']: r for r in reused['branches']}
    preserved = audit_preserved(args.snapshot, report, inventory, info, grid, imported)
    write_json(args.output/'preserved-audit.json', preserved)

    def no_integrations(*_args, **_kwargs):
        raise RuntimeError('Preparation must not integrate ODEs')
    producer.protocol_trajectory = no_integrations
    producer.scipy_protocol_trajectory = no_integrations
    restored = args.output/'restored-imports'
    restored.mkdir()
    rows = []
    historical = {r['record_id']: r for r in report['branches']}
    for bid, entry in sorted(imported.items()):
        require(digest(published/entry['file']) == entry['sha256'], 'Diagnostic branch digest differs')
        row = producer.compute_branch(bid, inventory['branches'][bid], restored, report, grid, path, info,
            imported=(read(published/entry['file']), published,
                      {'report_sha256': report['reused_report_sha256'], 'record_sha256': entry['sha256']}))
        if bid in historical:
            require(row == historical[bid], 'Imported record does not reproduce original bytes')
        rows.append({**row, 'matches_historical_record': bid in historical})
    remaining = select_remaining(inventory, preserved['complete_branch_ids'], list(imported))
    plan = {'schema_version': 1, 'model_id': inventory['model_id'], 'expected_full_branches': 323,
            'expected_selected_cases': 4, 'selected_case_keys': report['selected_case_keys'],
            'original_source_revision': SOURCE_REVISION, 'original_report_sha256': digest(args.snapshot/'report.json'),
            'inventory_sha256': report['inventory_sha256'], 'preservation_manifest_sha256': digest(args.manifest),
            'preserved_audit_sha256': digest(args.output/'preserved-audit.json'),
            'preserved_complete_branch_ids': preserved['complete_branch_ids'],
            'imported_branch_ids': sorted(imported), 'selected_branch_ids': remaining,
            'shard_count': 32, 'selection_rule': 'Every original branch without a verified complete preserved or published array set',
            'requests': report['requests'], 'acceptance': report['acceptance'],
            'case_recovery_claimed': False, 'full_model_coverage_claimed': False,
            'numerical_integrations_performed': 0}
    write_json(args.output/'continuation-plan.json', plan)
    write_json(args.output/'restoration-proof.json', {'release_sha256': RELEASE_SHA, 'branches': rows,
               'numerical_integrations_performed': 0, 'case_recovery_claimed': False})
    print(json.dumps({'full_inventory': 323, 'preserved_complete_branches': len(preserved['complete_branch_ids']),
                      'verified_preserved_arrays': preserved['verified_arrays'], 'published_imports': len(imported),
                      'branches_requiring_computation': len(remaining), 'selected_cases': 4,
                      'plan_sha256': digest(args.output/'continuation-plan.json')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot', 'manifest', 'inputs', 'archive', 'release-manifest', 'output'):
        parser.add_argument('--'+name, required=True, type=Path)
    prepare(parser.parse_args())
