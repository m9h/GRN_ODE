"""Authenticate all Ciliberto controls, including unsaved potential continuations.

This input adapter performs no integration and makes no recovery claim. Original
records remain separate from generated specifications. Existing numerical code,
legacy input validation and conditional-search rules are unchanged.
"""

import argparse
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import audit_branch, audit_case, require
from grn_memory.catalog_breaking import candidate_plans
from grn_memory.catalog_repeated import pulse_schedule, trains_for
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import inspect_model
from grn_memory.native_protocols import ResetTrain, sample_times
from scripts import run_ciliberto_full_diagnostics as fixed
from scripts.audit_breaking_shards import read_archives, source_hash
from scripts.prepare_ciliberto_full_inventory import build_inventory

MODEL = fixed.MODEL
SOURCE = fixed.SOURCE
ORIGINAL = ROOT / 'results/catalog-breaking-linux-28'
NUMERICAL_REVISION = '3d633d2f0b91c94cb947042032dc25224947322f'
SOURCE_REVISION = 'e07a53b219d995dde937e5a7ed7c923c463cff81'
FIRST_PLAN_SHA = '7a4f5cc4076de6d47a457220a8321d4b6849433c8eef599736c9c0a3f391f3c2'
EXTRA_FIXED_FILES = ('grn_memory/scipy_breaking_recovery.py', 'grn_memory/breaking_audit.py',
                     'grn_memory/breaking_scores.py', 'scripts/audit_scipy_breaking_cases.py',
                     'scripts/diagnose_scipy_breaking_controls.py',
                     'scripts/prepare_ciliberto_full_inventory.py')
read, write, digest = fixed.read, fixed.write, fixed.digest


def reconstruct(source, summaries, reference, config):
    """Generate every potential control independently of the observed paths."""
    plans = candidate_plans(reference)
    cases, specs, baseline = build_inventory(plans, summaries, reference, config)
    require(source['cases'] == cases and source['branches'] == specs
            and source['full_untreated_control'] == baseline
            and len(plans) == 622 and len(cases) == 74 and len(specs) == 7334,
            'Complete fixed case or control specification differs')
    occurrences = source['original_occurrences']
    require(set(occurrences) <= specs.keys() and baseline in occurrences,
            'Original occurrence lies outside the potential controls')
    origins = {}
    for bid in sorted(specs):
        rows = occurrences.get(bid, [])
        if bid in occurrences:
            require(bool(rows) and len({r['partition'] for r in rows}) == len(rows)
                    and all(type(r['partition']) is int and 0 <= r['partition'] < 16
                            and type(r['passed']) is bool
                            and isinstance(r['record_fingerprint'], str)
                            and len(r['record_fingerprint']) == 64 for r in rows),
                    'Original occurrence identity differs')
            origins[bid] = {'kind': 'observed_original', 'occurrences': rows}
        else:
            origins[bid] = {'kind': 'generated_potential', 'original_record_available': False}
    generated = sorted(specs.keys() - occurrences.keys())
    require(len(generated) == 200, 'All 200 unsaved potential controls are required')
    missing = {}
    for key, case in cases.items():
        index = case['original_summary']['shard_index']
        needed = {bid for trial in case['potential_trials'].values() for bid in trial['branches'].values()}
        observed = {bid for bid in needed if any(r['partition'] == index for r in occurrences.get(bid, []))}
        missing[key] = sorted(needed - observed)
    require(missing == source['potential_branches_absent_from_original_case_partition'],
            'Original case partition coverage differs')
    return {'schema_version': 1, 'source_kind': 'complete_ciliberto_failed_cases',
            'model_id': MODEL, 'model_sha256': source['model_sha256'],
            'source_revision': SOURCE_REVISION, 'source_inventory_sha256': fixed.INVENTORY_SHA,
            'calibration_sha256': source['calibration_sha256'],
            'cases': cases, 'branches': specs, 'branch_origins': origins,
            'generated_potential_branch_ids': generated,
            'missing_original_controls_by_case': missing,
            'full_untreated_control': baseline, 'expected_branches': len(specs),
            'expected_model_cases': len(plans), 'selected_cases': len(cases),
            'original_observed_branch_specifications': len(occurrences),
            'requests': source['requests'], 'acceptance': source['acceptance'],
            'conditional_search_must_be_recomputed': True,
            'case_recovery_claimed': False, 'full_model_coverage_claimed': False}


def prepare_inventory():
    """Load fixed source inputs and return the canonical inventory/model/grid."""
    fixed.check(ROOT / 'results/catalog-breaking-ciliberto-full-diagnostics-20261118',
                FIRST_PLAN_SHA, check_runtime=False)
    # The existing execution plan pins the numerical integrators and protocol;
    # these additional files pin the case compiler and conditional-search rules.
    first = read(ROOT / 'results/catalog-breaking-ciliberto-full-diagnostics-20261118/plan.json')
    for name in fixed.NUMERICAL_FILES:
        require(digest(ROOT / name) == first['runtime']['source_hashes'][name],
                'Frozen numerical source differs: ' + name)
    for name in EXTRA_FIXED_FILES:
        require(digest(ROOT / name) == source_hash(NUMERICAL_REVISION, name),
                'Frozen case source differs: ' + name)
    source = read(SOURCE / 'inventory.json')
    audit = read(ORIGINAL / 'audit.json')
    reference_path = ROOT / 'results/catalog-repeated' / (MODEL + '.json')
    reference = read(reference_path)
    require(digest(reference_path) == source['calibration_sha256']
            and reference['status'] == 'passed', 'Validated calibration differs')
    reports = [read(ORIGINAL / f'shard-{i}' / (MODEL + '.json')) for i in range(16)]
    original = reports[0]
    require(all(r['configuration'] == original['configuration']
                and r['model_sha256'] == source['model_sha256']
                and r['reference_file_sha256'] == source['calibration_sha256'] for r in reports),
            'Original source configuration differs across partitions')
    inventory = reconstruct(source, audit['case_summaries'], reference, original['configuration'])
    path = ROOT / 'models' / (MODEL + '.xml')
    info = inspect_model(path)
    require(info['sha256'] == inventory['model_sha256'], 'SBML model differs')
    possible = trains_for(pulse_schedule(), {}) + [ResetTrain(t, t + 100., {})
                for t in (1010., 1210., 1410., 1610., 1810., 2010.)]
    grid = sample_times(2210., .01, possible, post_reset_offset=1e-5)
    return inventory, path, info, grid


def expected_records(inventory, index):
    return {bid: row for bid, origin in inventory['branch_origins'].items()
            for row in origin.get('occurrences', []) if row['partition'] == index}


def verify_records(inventory, index, records, report, observables):
    expected = expected_records(inventory, index)
    require(set(records) == set(expected), 'Original partition record inventory differs')
    for bid, record in records.items():
        row = expected[bid]
        require(record['record_id'] == bid and fingerprint(record) == row['record_fingerprint']
                and record['specification'] == inventory['branches'][bid]
                and record['passed'] == row['passed'], 'Original partition record differs')
        audit_branch(record, report, observables)


def verify_cases(inventory, index, cases, records, report, reference):
    expected = {key for key, case in inventory['cases'].items()
                if case['original_summary']['shard_index'] == index}
    require(set(cases) == expected, 'Original failed-case partition inventory differs')
    results = {}
    for key in sorted(expected):
        selected = inventory['cases'][key]
        case = cases[key]
        require(case['record_id'] == fingerprint(selected['original_plan']) and case['case_key'] == key,
                'Original case identity differs')
        summary, used, unknown = audit_case(case, selected['original_plan'], records, report, reference)
        require({**summary, 'shard_index': index} == selected['original_summary']
                and summary == report['cases'][key], 'Original case audit differs')
        require(used <= set(records), 'Original case requires an uncaptured record')
        results[key] = {'partition': index, 'case': case, 'summary': summary,
                        'observed_branch_ids': sorted(used),
                        'unresolved_conditional_decisions': unknown}
    return results


def write_records(path, records):
    with path.open('xb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as stream:
        for bid in sorted(records):
            stream.write((json.dumps(records[bid], sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode())


def read_records(path):
    result = {}
    with gzip.open(path, 'rt') as stream:
        for line in stream:
            record = json.loads(line)
            bid = record['record_id']
            require(bid not in result, 'Duplicate original branch record')
            result[bid] = record
    return result


def capture(original_root, output):
    require(not output.exists(), 'Use a new full-control input directory')
    inventory, _, info, grid = prepare_inventory()
    reference = read(ROOT / 'results/catalog-repeated' / (MODEL + '.json'))
    output.mkdir(parents=True)
    write(output / 'inventory.json', inventory)
    all_cases, partitions = {}, []
    provenance = read(ORIGINAL / 'source-artifacts.json')
    for index in range(16):
        directory = original_root / f'shard-{index}'
        # Check the original partition metadata and the compressed archives
        # against the tracked, release-verified source, before selecting records.
        for name, sha in provenance['partitions'][index]['copied_metadata_sha256'].items():
            require(digest(directory / name) == sha, 'Original partition metadata differs')
        report_path = directory / (MODEL + '.json')
        require(digest(report_path) == digest(ORIGINAL / f'shard-{index}' / (MODEL + '.json')),
                'Original partition report differs')
        manifest = read(directory / 'shard.json')
        require(manifest['git_revision'] == SOURCE_REVISION, 'Original producer revision differs')
        report = read(report_path)
        all_records = read_archives(directory, report, 'branches')
        ids = expected_records(inventory, index)
        require(set(ids) <= all_records.keys(), 'An original control is missing from the release')
        records = {bid: all_records[bid] for bid in ids}
        verify_records(inventory, index, records, report, info['observables'])
        original_cases = read_archives(directory, report, 'cases')
        cases = {key: original_cases[fingerprint(case['original_plan'])]
                 for key, case in inventory['cases'].items() if case['original_summary']['shard_index'] == index}
        checked = verify_cases(inventory, index, cases, records, report, reference)
        all_cases.update(checked)
        name = f'original-branches-{index:02d}.jsonl.gz'
        write_records(output / name, records)
        partitions.append({'index': index, 'file': name, 'records': len(records), 'cases': sorted(checked),
                           'source_report_sha256': digest(report_path)})
        print(json.dumps({'partition': index, 'verified_original_records': len(records),
                          'verified_original_failed_cases': len(checked)}), flush=True)
    require(len(all_cases) == 74, 'All original failed cases are required')
    write(output / 'original-cases.json', all_cases)
    files = {p.name: {'sha256': digest(p), 'bytes': p.stat().st_size} for p in sorted(output.iterdir())}
    manifest = {'schema_version': 1, 'model_id': MODEL, 'source_inventory_sha256': fixed.INVENTORY_SHA,
                'original_source_revision': SOURCE_REVISION, 'files': files, 'partitions': partitions,
                'expected_branches': 7334, 'selected_cases': 74, 'generated_potential_branches': 200,
                'sample_count': len(grid), 'numerical_integrations_performed': 0,
                'case_recovery_claimed': False, 'full_model_coverage_claimed': False}
    write(output / 'manifest.json', manifest)
    print(json.dumps({'manifest_sha256': digest(output / 'manifest.json'),
                      'bytes': sum(row['bytes'] for row in files.values())}), flush=True)
    return manifest


def validate(directory, manifest_sha):
    require(digest(directory / 'manifest.json') == manifest_sha, 'Pinned full-control manifest differs')
    manifest = read(directory / 'manifest.json')
    require(manifest['schema_version'] == 1 and manifest['model_id'] == MODEL
            and manifest['source_inventory_sha256'] == fixed.INVENTORY_SHA
            and manifest['original_source_revision'] == SOURCE_REVISION
            and manifest['expected_branches'] == 7334 and manifest['selected_cases'] == 74
            and manifest['generated_potential_branches'] == 200
            and manifest['numerical_integrations_performed'] == 0
            and manifest['case_recovery_claimed'] is False and manifest['full_model_coverage_claimed'] is False,
            'Complete full-control manifest scope differs')
    expected_files = {'inventory.json', 'original-cases.json'} | {f'original-branches-{i:02d}.jsonl.gz' for i in range(16)}
    require(set(manifest['files']) == expected_files, 'Full-control file inventory differs')
    for name, item in manifest['files'].items():
        path = directory / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == item['bytes']
                and digest(path) == item['sha256'], 'Full-control file checksum or size differs')
    inventory, _, info, grid = prepare_inventory()
    require(read(directory / 'inventory.json') == inventory and manifest['sample_count'] == len(grid),
            'Canonical full-control inventory or grid differs')
    cases = read(directory / 'original-cases.json')
    require(set(cases) == set(inventory['cases']), 'All 74 original cases are required')
    require([row['index'] for row in manifest['partitions']] == list(range(16)), 'All 16 original partitions are required')
    reference = read(ROOT / 'results/catalog-repeated' / (MODEL + '.json'))
    record_count = 0
    for row in manifest['partitions']:
        index = row['index']
        require(row['file'] == f'original-branches-{index:02d}.jsonl.gz', 'Original branch archive path differs')
        report_path = ORIGINAL / f'shard-{index}' / (MODEL + '.json')
        require(row['source_report_sha256'] == digest(report_path), 'Original report identity differs')
        records = read_records(directory / row['file'])
        require(len(records) == row['records'], 'Original partition record count differs')
        verify_records(inventory, index, records, read(report_path), info['observables'])
        selected = {key: c['case'] for key, c in cases.items() if c['partition'] == index}
        checked = verify_cases(inventory, index, selected, records, read(report_path), reference)
        require(sorted(checked) == row['cases'] and all(cases[key] == value for key, value in checked.items()),
                'Original case evidence does not reproduce')
        record_count += len(records)
    return {'manifest_sha256': manifest_sha, 'complete_input_scope_verified': True,
            'selected_cases': 74, 'potential_branches': 7334,
            'original_observed_branch_specifications': inventory['original_observed_branch_specifications'],
            'original_branch_records_across_partitions': record_count, 'generated_potential_branches': 200,
            'sample_count': len(grid), 'observables': len(info['observables']),
            'numerical_integrations_performed': 0, 'case_recovery_claimed': False,
            'full_model_coverage_claimed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    cap = sub.add_parser('capture')
    cap.add_argument('--original-root', type=Path, required=True)
    cap.add_argument('--output', type=Path, required=True)
    check = sub.add_parser('check')
    check.add_argument('--inputs', type=Path, required=True)
    check.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args()
    if args.operation == 'capture':
        capture(args.original_root, args.output)
    else:
        print(json.dumps(validate(args.inputs, args.manifest_sha256)), flush=True)
