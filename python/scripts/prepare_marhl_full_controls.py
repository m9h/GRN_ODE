"""Reconstruct all potential controls for the twelve failed Marhl breaking cases.

This reads the pinned original four-partition evidence and the published Radau
selection. It performs no integration and does not promote any numerical result.
"""

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import audit_case, require
from grn_memory.catalog_breaking import candidate_plans
from grn_memory.catalog_repeated import pulse_schedule, trains_for
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import inspect_model
from grn_memory.native_protocols import ResetTrain, sample_times
from grn_memory.scipy_breaking_recovery import common_eligibility, potential_trials, trial_specifications
from scripts.audit_breaking_shards import audit, digest, read_archives, source_hash

BASE = '079e35d8bc0795f427b6cb5b8514f35830f01909'
MODEL = 'BIOMD0000000039'
SOURCE = ROOT / 'results/catalog-breaking-linux-30'
DIAGNOSTIC = ROOT / 'results/catalog-breaking-marhl30-radau-20261114'
CODE_FILES = (
    'grn_memory/breaking_audit.py', 'grn_memory/breaking_scores.py',
    'grn_memory/breaking_shards.py', 'grn_memory/catalog_breaking.py',
    'grn_memory/catalog_repeated.py', 'grn_memory/catalog_runner.py',
    'grn_memory/catalog_memory.py', 'grn_memory/catalog_validation.py',
    'grn_memory/native_protocols.py', 'grn_memory/scipy_breaking_recovery.py',
    'scripts/audit_breaking_shards.py',
)


def read(path):
    return json.loads(path.read_text())


def pin(path, sources):
    name = path.relative_to(ROOT).as_posix()
    require(not path.is_symlink() and path.is_file(), 'Pinned regular file required: ' + name)
    sha = digest(path)
    require(sha == source_hash(BASE, name), 'Pinned source differs: ' + name)
    sources[name] = {'sha256': sha, 'bytes': path.stat().st_size}


def portable(audit_result):
    result = deepcopy(audit_result)
    for part in result['partitions']:
        part['directory'] = 'results/catalog-breaking-linux-30/' + Path(part['directory']).name
    return result


def compile_scope(plans, summaries, reference, config):
    cases, branches = {}, {}
    for key in sorted(k for k, row in summaries.items() if row['status'] != 'passed'):
        plan = plans[key]
        common_eligibility(plan)  # Reject conflicting original engine eligibility.
        trials = {}
        for name, breakers in potential_trials(plan, reference).items():
            roles = {}
            for role, spec in trial_specifications(plan, breakers, reference, config).items():
                bid = fingerprint(spec)
                require(bid not in branches or branches[bid] == spec, 'Conflicting branch specification')
                branches[bid], roles[role] = spec, bid
            trials[name] = {'breakers': breakers, 'branches': roles}
        cases[key] = {'original_plan': deepcopy(plan), 'original_summary': deepcopy(summaries[key]),
                      'shared_source_eligibility': {response: deepcopy(row['roadrunner'])
                                                    for response, row in plan['responses'].items()},
                      'potential_trials': trials}
    baseline = {'reset_trains': [], 'stop': 2210., 'integration_settings': deepcopy(config['integration_settings'])}
    baseline_id = fingerprint(baseline)
    branches[baseline_id] = baseline
    return cases, branches, baseline_id


def annotate(cases, specs, reports, originals, original_cases, reference):
    origins, records, failed = {}, 0, set()
    for index, rows in enumerate(originals):
        for bid, row in rows.items():
            if bid not in specs:
                require(row['passed'], 'An original failure is outside the selected cases')
                continue
            require(row['specification'] == specs[bid], 'Original specification differs')
            origins.setdefault(bid, []).append({'partition': index, 'passed': row['passed'],
                                                'record_fingerprint': fingerprint(row)})
            records += 1
            if not row['passed']:
                failed.add(bid)
    for key, case in cases.items():
        index = case['original_summary']['shard_index']
        record = original_cases[index][fingerprint(case['original_plan'])]
        summary, used, unknown = audit_case(record, case['original_plan'], originals[index], reports[index], reference)
        require({**summary, 'shard_index': index} == case['original_summary']
                and summary == reports[index]['cases'][key], 'Original case summary does not reproduce')
        required = {bid for trial in case['potential_trials'].values() for bid in trial['branches'].values()}
        require(used <= required, 'Original case uses a branch outside its potential inventory')
        case.update(original_record_id=record['record_id'], original_record_fingerprint=fingerprint(record),
                    observed_branch_ids=sorted(used),
                    missing_original_partition_branches=sorted(required - originals[index].keys()),
                    original_unresolved_conditional_decisions=unknown)
    return {bid: ({'kind': 'observed_original', 'occurrences': origins[bid]} if bid in origins
                  else {'kind': 'generated_potential', 'original_record_available': False})
            for bid in sorted(specs)}, records, sorted(failed)


def build():
    sources = {}
    reference_path = ROOT / 'results/catalog-repeated' / (MODEL + '.json')
    for path in [ROOT / name for name in CODE_FILES] + [SOURCE / 'audit.json', DIAGNOSTIC / 'plan.json',
            ROOT / 'models/catalog.json', ROOT / 'models' / (MODEL + '.xml'), reference_path]:
        pin(path, sources)
    directories = [SOURCE / f'shard-{i}' for i in range(4)]
    reports, originals, original_cases, captured = [], [], [], []
    diagnostic = read(DIAGNOSTIC / 'plan.json')
    require([p['shard_index'] for p in diagnostic['partitions']] == list(range(4)),
            'All original diagnostic partitions are required')
    for index, directory in enumerate(directories):
        report_path = directory / (MODEL + '.json')
        report = read(report_path)
        for path in [directory / 'shard.json', report_path] + [directory / row['file']
                for kind in ('branches', 'cases') for row in report['evidence_archives'][kind]]:
            pin(path, sources)
        part = diagnostic['partitions'][index]
        capture_path = DIAGNOSTIC / part['source_evidence_file']
        pin(capture_path, sources)
        capture = read(capture_path)
        require(digest(capture_path) == part['source_evidence_sha256']
                and digest(report_path) == part['source_report_sha256'] == capture['original_report_sha256']
                and capture['original_report'] == report
                and digest(directory / 'shard.json') == part['source_manifest_sha256'],
                'Published diagnostic provenance differs')
        rows = read_archives(directory, report, 'branches')
        failures = {bid: row for bid, row in rows.items() if not row['passed']}
        require(capture['failed_branches'] == [failures[bid] for bid in sorted(failures)]
                and sorted(failures) == part['failed_branch_ids'], 'Complete published failure selection differs')
        reports.append(report)
        originals.append(rows)
        original_cases.append(read_archives(directory, report, 'cases'))
        captured.extend({'partition': index, 'branch_id': bid, 'record_fingerprint': fingerprint(row)}
                        for bid, row in sorted(failures.items()))
    original_audit = portable(audit(directories, 30))
    require(original_audit == read(SOURCE / 'audit.json'), 'Original whole-model audit does not reproduce')
    require(original_audit['cases'] == 38 and original_audit['passed_cases'] == 26
            and original_audit['complete_case_coverage'] and not original_audit['unresolved_conditional_decisions'],
            'Complete original Marhl scope differs')
    reference = read(reference_path)
    config = reports[0]['configuration']
    require(all(r['configuration'] == config for r in reports), 'Cross-partition configuration differs')
    plans = candidate_plans(reference)
    cases, specs, baseline = compile_scope(plans, original_audit['case_summaries'], reference, config)
    origins, records, failed = annotate(cases, specs, reports, originals, original_cases, reference)
    require(len(cases) == 12 and len(specs) == 380 and len(captured) == 30 and len(failed) == 29,
            'All original failed cases and potential controls are required')
    generated = sorted(bid for bid, origin in origins.items() if origin['kind'] == 'generated_potential')
    require(len(generated) == 88 and records == 346, 'Original versus generated branch inventory differs')
    possible = trains_for(pulse_schedule(), {}) + [ResetTrain(t, t + 100., {})
                for t in (1010., 1210., 1410., 1610., 1810., 2010.)]
    grid = sample_times(2210., .01, possible, post_reset_offset=1e-5)
    info = inspect_model(ROOT / 'models' / (MODEL + '.xml'))
    observations = {}
    for bid, spec in specs.items():
        times = grid[grid <= spec['stop']]
        trains = [ResetTrain(**t) for t in spec['reset_trains']]
        observations[bid] = {'samples': len(times), 'sample_grid_sha256': hashlib.sha256(times.tobytes()).hexdigest(),
                            'reset_counts': [len(t.indices()) if t.values else 0 for t in trains]}
    return {'schema_version': 1, 'model_id': MODEL, 'network': 30, 'source_revision': BASE,
            'model_sha256': info['sha256'], 'observables': info['observables'],
            'original_model_cases': 38, 'original_passing_cases': 26, 'selected_cases': len(cases),
            'original_audit_sha256': digest(SOURCE / 'audit.json'), 'source_files': sources,
            'original_audit_reproduced': True, 'cases': cases, 'branches': specs,
            'branch_origins': origins, 'branch_observations': observations,
            'full_untreated_control': baseline, 'expected_branches': len(specs),
            'original_observed_branch_specifications': len(specs) - len(generated),
            'original_selected_branch_records': records, 'generated_potential_branch_ids': generated,
            'original_failed_branch_records': captured, 'diagnostic_branch_ids': failed,
            'other_required_branch_ids': sorted(specs.keys() - set(failed)),
            'horizon_counts': dict(sorted(Counter(str(spec['stop']) for spec in specs.values()).items())),
            'acceptance': {'rtol': 2e-5, 'atol': 1e-7},
            'integration_settings_in_specifications': 'Original settings identify source branches; new solver requests are not declared here.',
            'numerical_integrations_performed': 0, 'raw_trajectory_arrays_verified': 0,
            'conditional_search_must_be_recomputed': True, 'case_recovery_claimed': False,
            'full_model_coverage_claimed': False}


def check(path):
    require(not path.is_symlink() and path.is_file(), 'Inventory must be a regular file')
    actual = read(path)
    expected = build()
    require(actual == expected, 'Complete inventory does not reproduce from the pinned original evidence')
    return summary(actual, path)


def summary(inventory, path):
    return {k: inventory[k] for k in ('model_id', 'selected_cases', 'expected_branches',
            'original_observed_branch_specifications', 'original_selected_branch_records',
            'horizon_counts', 'numerical_integrations_performed', 'raw_trajectory_arrays_verified',
            'case_recovery_claimed', 'full_model_coverage_claimed')} | {
            'inventory_sha256': digest(path), 'generated_potential_branches': len(inventory['generated_potential_branch_ids']),
            'diagnostic_branches': len(inventory['diagnostic_branch_ids']),
            'other_required_branches': len(inventory['other_required_branch_ids'])}


def capture(path):
    require(not path.exists() and not path.is_symlink(), 'Use a new inventory path')
    inventory = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(inventory, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return summary(inventory, path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['capture', 'check'])
    parser.add_argument('--inventory', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps((capture if args.operation == 'capture' else check)(args.inventory), indent=2))
