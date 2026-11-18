"""Preserve every original Rohwer failed case and every potential control.

The 750 queued diagnostics and 10,924 later controls partition all 11,674
required branches. Original records remain separate from generated controls.
This adapter performs no integration and makes no recovery claim.
"""

import argparse
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import audit_branch, audit_case
from grn_memory.catalog_breaking import candidate_plans
from grn_memory.catalog_repeated import pulse_schedule, trains_for
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import inspect_model
from grn_memory.native_protocols import ResetTrain, sample_times
from grn_memory.scipy_breaking_recovery import common_eligibility, potential_trials, trial_specifications
from scripts import run_rohwer_breaking_diagnostics as source
from scripts.audit_breaking_continuations import evaluate
from scripts.audit_breaking_shards import read_archives, source_hash

read, write, digest, require = source.read, source.write, source.digest, source.require
INPUTS = ROOT / 'results/catalog-breaking-rohwer-diagnostics-20261118'
PLAN_SHA = 'ab0f50d411a929a887fdf5132958502ec11a2af620cd577b8fc40f5994b4b9f0'
NUMERICAL_REVISION = '12c0693df1d68d1736b274a9364e1ef7b2533b06'
CASE_FILES = ('grn_memory/scipy_breaking_recovery.py', 'grn_memory/breaking_audit.py',
              'grn_memory/breaking_scores.py', 'scripts/audit_scipy_breaking_cases.py',
              'scripts/audit_breaking_shards.py', 'scripts/audit_breaking_continuations.py')


def compile_cases(plans, summaries, reference, config):
    cases, specs = {}, {}
    for key in sorted(k for k, row in summaries.items() if row['status'] != 'passed'):
        plan = plans[key]
        eligibility = common_eligibility(plan)
        trials = {}
        for name, breakers in potential_trials(plan, reference).items():
            roles = {}
            for role, spec in trial_specifications(plan, breakers, reference, config).items():
                bid = fingerprint(spec)
                require(bid not in specs or specs[bid] == spec, 'Conflicting branch specification')
                specs[bid], roles[role] = spec, bid
            trials[name] = {'breakers': breakers, 'branches': roles}
        cases[key] = {'original_plan': plan, 'original_summary': summaries[key],
                      'shared_source_eligibility': eligibility, 'potential_trials': trials}
    baseline = {'reset_trains': [], 'stop': 2210., 'integration_settings': config['integration_settings']}
    baseline_id = fingerprint(baseline)
    specs[baseline_id] = baseline
    return cases, specs, baseline_id


def prepare_scope(*, check_runtime=False):
    plan = source.check(INPUTS, PLAN_SHA, check_runtime=check_runtime)
    for name in source.NUMERICAL_FILES:
        require(digest(ROOT / name) == plan['runtime']['source_hashes'][name], 'Frozen numerical source differs: ' + name)
    for name in CASE_FILES:
        require(digest(ROOT / name) == source_hash(NUMERICAL_REVISION, name), 'Frozen case source differs: ' + name)
    sources = [read(INPUTS / row['file']) for row in plan['source_partitions']]
    reports = [s['original_report'] for s in sources]
    reference_path = ROOT / 'results/catalog-repeated' / (source.MODEL + '.json')
    reference = read(reference_path)
    config = reports[0]['configuration']
    require(reference['status'] == 'passed' and reference['model_sha256'] == plan['model_sha256']
            and all(r['configuration'] == config and r['reference_file_sha256'] == digest(reference_path)
                    and r['reference_fingerprint'] == reference['fingerprint'] for r in reports),
            'Original calibration or cross-partition configuration differs')
    plans = candidate_plans(reference)
    original_audit = read(source.SOURCE / 'audit.json')
    require(len(plans) == 260 and fingerprint(plans) == config['candidate_plan_sha256'],
            'Complete original candidate inventory differs')
    cases, specs, baseline = compile_cases(plans, original_audit['case_summaries'], reference, config)
    diagnostics = {row['record_id']: row for part in plan['partitions'] for row in part['branches']}
    require(len(cases) == 123 and len(specs) == 11674 and len(diagnostics) == 750
            and set(diagnostics) <= specs.keys(), 'All original failed cases and diagnostic branches are required')
    later = sorted(specs.keys() - diagnostics.keys())
    require(len(later) == 10924, 'All remaining potential controls are required')
    for captured in sources:
        for record in captured['failed_branches']:
            require(specs[record['record_id']] == record['specification'], 'Original failed specification differs')
    scope = {'schema_version': 1, 'model_id': source.MODEL, 'model_sha256': plan['model_sha256'],
             'original_model_cases': 260, 'original_passing_cases': 137, 'selected_cases': 123,
             'original_audit_sha256': plan['original_audit_sha256'],
             'original_selection_sha256': plan['source_selection_sha256'],
             'source_verification_sha256': digest(INPUTS / 'source-verification.json'),
             'diagnostic_plan_sha256': PLAN_SHA, 'calibration_sha256': digest(reference_path),
             'cases': cases, 'branches': specs, 'full_untreated_control': baseline,
             'expected_branches': 11674, 'queued_diagnostics': diagnostics,
             'later_control_ids': later, 'later_control_count': 10924,
             'conditional_search_must_be_recomputed': True,
             'case_recovery_claimed': False, 'full_model_coverage_claimed': False}
    model = ROOT / 'models' / (source.MODEL + '.xml')
    info = inspect_model(model)
    require(info['sha256'] == plan['model_sha256'], 'SBML model differs')
    possible = trains_for(pulse_schedule(), {}) + [ResetTrain(t, t + 100., {})
                for t in (1010., 1210., 1410., 1610., 1810., 2010.)]
    grid = sample_times(2210., .01, possible, post_reset_offset=1e-5)
    return scope, sources, reference, info, grid


def check_records(index, records, scope, captured, observables):
    report = captured['original_report']
    failed = {r['record_id']: r for r in captured['failed_branches']}
    require(set(failed) <= records.keys() <= scope['branches'].keys(),
            'Selected original records omit a diagnostic or add an unrelated branch')
    for bid, row in records.items():
        require(row['record_id'] == bid and row['specification'] == scope['branches'][bid],
                'Original selected branch identity differs')
        if bid in failed:
            require(row == failed[bid], 'Original failed record differs from frozen diagnostic capture')
        audit_branch(row, report, observables)
    return {bid: {'partition': index, 'passed': row['passed'], 'record_fingerprint': fingerprint(row)}
            for bid, row in records.items()}


def check_cases(index, cases, records, scope, report, reference):
    expected = {k for k, row in scope['cases'].items() if row['original_summary']['shard_index'] == index}
    require(set(cases) == expected, 'Every original failed case in this partition is required')
    checked = {}
    for key in sorted(expected):
        selected, original = scope['cases'][key], cases[key]
        require(original['record_id'] == fingerprint(selected['original_plan']) and original['case_key'] == key,
                'Original case identity differs')
        summary, used, unknown = audit_case(original, selected['original_plan'], records, report, reference)
        require({**summary, 'shard_index': index} == selected['original_summary']
                and summary == report['cases'][key] and used <= records.keys(), 'Original case audit differs')
        checked[key] = {'partition': index, 'case': original, 'summary': summary,
                        'observed_branch_ids': sorted(used), 'unresolved_conditional_decisions': unknown}
    return checked


def add_origins(scope, occurrences):
    require(set(occurrences) <= scope['branches'].keys(), 'Original occurrence is outside full scope')
    origins = {}
    for bid in sorted(scope['branches']):
        if bid in occurrences:
            rows = occurrences[bid]
            require(rows and len({r['partition'] for r in rows}) == len(rows)
                    and all(type(r['partition']) is int and 0 <= r['partition'] < 16
                            and type(r['passed']) is bool and isinstance(r['record_fingerprint'], str)
                            and len(r['record_fingerprint']) == 64 for r in rows), 'Original occurrence identity differs')
            origins[bid] = {'kind': 'observed_original', 'occurrences': sorted(rows, key=lambda r: r['partition'])}
        else:
            origins[bid] = {'kind': 'generated_potential', 'original_record_available': False}
    missing = {}
    for key, case in scope['cases'].items():
        index = case['original_summary']['shard_index']
        needed = {bid for trial in case['potential_trials'].values() for bid in trial['branches'].values()}
        missing[key] = sorted(bid for bid in needed
                              if not any(r['partition'] == index for r in occurrences.get(bid, [])))
    return {**scope, 'branch_origins': origins,
            'generated_potential_branch_ids': sorted(set(scope['branches']) - set(occurrences)),
            'original_observed_branch_specifications': len(occurrences),
            'missing_original_controls_by_case': missing}


def write_records(path, records):
    with path.open('xb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as stream:
        for bid in sorted(records):
            stream.write((json.dumps(records[bid], sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode())


def read_records(path):
    records = {}
    with gzip.open(path, 'rt') as stream:
        for line in stream:
            row = json.loads(line)
            require(row['record_id'] not in records, 'Duplicate original record')
            records[row['record_id']] = row
    return records


def capture(collection_root, output):
    require(not output.exists(), 'Use a new full-control capture directory')
    scope, sources, reference, info, grid = prepare_scope()
    verified = evaluate(read(source.SOURCE / 'selection-plan.json'), [collection_root])
    audit = verified.pop('model_audit')
    require(source.portable(audit) == source.portable(read(source.SOURCE / 'audit.json'))
            and verified == read(INPUTS / 'source-verification.json'), 'Original whole-model evidence does not reproduce')
    require(audit['complete_case_coverage'] and audit['cases'] == 260 and audit['passed_cases'] == 137,
            'Complete original case scope differs')
    output.mkdir(parents=True)
    occurrences, cases, partitions = {}, {}, []
    for index, part in enumerate(audit['partitions']):
        directory = Path(part['directory'])
        captured = sources[index]
        report_path = directory / (source.MODEL + '.json')
        require(digest(report_path) == captured['original_report_sha256']
                and read(report_path) == captured['original_report'], 'Original partition report differs')
        report = captured['original_report']
        all_records = read_archives(directory, report, 'branches')
        records = {bid: row for bid, row in all_records.items() if bid in scope['branches']}
        for bid, row in check_records(index, records, scope, captured, info['observables']).items():
            occurrences.setdefault(bid, []).append(row)
        original_cases = read_archives(directory, report, 'cases')
        selected = {key: original_cases[fingerprint(row['original_plan'])] for key, row in scope['cases'].items()
                    if row['original_summary']['shard_index'] == index}
        checked = check_cases(index, selected, records, scope, report, reference)
        cases.update(checked)
        name = f'original-branches-{index:02d}.jsonl.gz'
        write_records(output / name, records)
        partitions.append({'index': index, 'file': name, 'records': len(records), 'cases': sorted(checked),
                           'source_report_sha256': captured['original_report_sha256']})
        print({'partition': index, 'verified_original_records': len(records), 'failed_cases': len(checked)}, flush=True)
    inventory = add_origins(scope, occurrences)
    write(output / 'inventory.json', inventory)
    write(output / 'original-cases.json', cases)
    files = {p.name: {'sha256': digest(p), 'bytes': p.stat().st_size} for p in sorted(output.iterdir())}
    manifest = {'schema_version': 1, 'model_id': source.MODEL, 'diagnostic_plan_sha256': PLAN_SHA,
                'source_verification_sha256': scope['source_verification_sha256'], 'files': files,
                'partitions': partitions, 'expected_branches': 11674, 'selected_cases': 123,
                'queued_diagnostic_branches': 750, 'later_control_branches': 10924,
                'generated_potential_branches': len(inventory['generated_potential_branch_ids']),
                'sample_count': len(grid), 'observables': len(info['observables']),
                'original_whole_model_audit_reproduced': True, 'numerical_integrations_performed': 0,
                'case_recovery_claimed': False, 'full_model_coverage_claimed': False}
    write(output / 'manifest.json', manifest)
    print({'manifest_sha256': digest(output / 'manifest.json'), 'bytes': sum(r['bytes'] for r in files.values()),
           'generated_potential_branches': manifest['generated_potential_branches']}, flush=True)
    return manifest


def validate(directory, manifest_sha, *, check_runtime=False):
    require(not (directory / 'manifest.json').is_symlink()
            and digest(directory / 'manifest.json') == manifest_sha, 'Pinned manifest differs')
    manifest = read(directory / 'manifest.json')
    require(manifest['schema_version'] == 1 and manifest['model_id'] == source.MODEL
            and manifest['diagnostic_plan_sha256'] == PLAN_SHA and manifest['expected_branches'] == 11674
            and manifest['selected_cases'] == 123 and manifest['queued_diagnostic_branches'] == 750
            and manifest['later_control_branches'] == 10924 and manifest['original_whole_model_audit_reproduced'] is True
            and manifest['numerical_integrations_performed'] == 0 and manifest['case_recovery_claimed'] is False
            and manifest['full_model_coverage_claimed'] is False, 'Full-control manifest scope differs')
    expected_files = {'inventory.json', 'original-cases.json'} | {f'original-branches-{i:02d}.jsonl.gz' for i in range(16)}
    require(set(manifest['files']) == expected_files, 'Complete input file inventory differs')
    for name, item in manifest['files'].items():
        path = directory / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == item['bytes']
                and digest(path) == item['sha256'], 'Input file size or checksum differs')
    scope, sources, reference, info, grid = prepare_scope(check_runtime=check_runtime)
    require(manifest['source_verification_sha256'] == scope['source_verification_sha256']
            and manifest['sample_count'] == len(grid) and manifest['observables'] == len(info['observables']),
            'Source verification, model observables or full grid differs')
    cases = read(directory / 'original-cases.json')
    require(set(cases) == set(scope['cases']), 'All 123 original failed cases are required')
    require([r['index'] for r in manifest['partitions']] == list(range(16)), 'All 16 original partitions are required')
    occurrences, record_count = {}, 0
    for row in manifest['partitions']:
        index = row['index']
        require(row['file'] == f'original-branches-{index:02d}.jsonl.gz'
                and row['source_report_sha256'] == sources[index]['original_report_sha256'],
                'Original partition provenance differs')
        records = read_records(directory / row['file'])
        require(len(records) == row['records'], 'Original partition record count differs')
        for bid, occurrence in check_records(index, records, scope, sources[index], info['observables']).items():
            occurrences.setdefault(bid, []).append(occurrence)
        selected = {key: c['case'] for key, c in cases.items() if c['partition'] == index}
        checked = check_cases(index, selected, records, scope, sources[index]['original_report'], reference)
        require(sorted(checked) == row['cases'] and all(cases[key] == value for key, value in checked.items()),
                'Original case evidence does not reproduce')
        record_count += len(records)
    inventory = add_origins(scope, occurrences)
    require(read(directory / 'inventory.json') == inventory
            and manifest['generated_potential_branches'] == len(inventory['generated_potential_branch_ids']),
            'Complete canonical inventory, origins or generated controls differ')
    return {'manifest_sha256': manifest_sha, 'complete_input_scope_verified': True,
            'selected_cases': 123, 'potential_branches': 11674, 'queued_diagnostic_branches': 750,
            'later_control_branches': 10924, 'original_observed_branch_specifications': len(occurrences),
            'original_branch_records_across_partitions': record_count,
            'generated_potential_branches': len(inventory['generated_potential_branch_ids']),
            'cases_with_missing_original_controls': sum(bool(v) for v in inventory['missing_original_controls_by_case'].values()),
            'sample_count': len(grid), 'observables': len(info['observables']),
            'numerical_runtime_checked': check_runtime, 'numerical_integrations_performed': 0,
            'case_recovery_claimed': False, 'full_model_coverage_claimed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    cap = sub.add_parser('capture')
    cap.add_argument('--collection-root', type=Path, required=True)
    cap.add_argument('--output', type=Path, required=True)
    check = sub.add_parser('check')
    check.add_argument('--inputs', type=Path, required=True)
    check.add_argument('--manifest-sha256', required=True)
    check.add_argument('--check-runtime', action='store_true')
    args = parser.parse_args()
    if args.operation == 'capture':
        capture(args.collection_root, args.output)
    else:
        print(json.dumps(validate(args.inputs, args.manifest_sha256, check_runtime=args.check_runtime)), flush=True)
