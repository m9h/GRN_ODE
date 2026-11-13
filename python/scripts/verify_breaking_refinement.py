"""Verify native refinement records against a fully audited original model.

This checks provenance, complete failure coverage, requests, observations and
recorded comparison consistency. The producer saves no raw arrays, so this is
not an independent pointwise recomputation or a complete-case recovery audit.
"""

import argparse
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import audit_comparison, require
from grn_memory.catalog_breaking import trial_windows
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_repeated import pulse_schedule, trains_for
from grn_memory.catalog_validation import PACKAGES, inspect_model
from grn_memory.native_protocols import ResetTrain, sample_times
from scripts.audit_breaking_catalog import audit_model
from scripts.audit_breaking_shards import digest, read_archives, source_hash


ENGINES = ('roadrunner', 'copasi')
LABELS = tuple(e+'_'+r for e in ENGINES for r in ('original', 'tight', 'tighter'))
PAIRS = [(f'roadrunner_{r}', f'copasi_{r}') for r in ('original', 'tight', 'tighter')]
PAIRS += [(e+'_'+a, e+'_'+b) for e in ENGINES
          for a, b in (('original', 'tight'), ('tight', 'tighter'))]
REQUIRED = {a+'_vs_'+b for a, b in PAIRS if 'original' not in a+b}
IMPLEMENTATIONS = {'native_protocols.py', 'catalog_validation.py', 'catalog_repeated.py',
                   'catalog_breaking.py', 'timed_drives.py'}


def read(path):
    return json.loads(path.read_text())


def verify_branch(record, original, observables):
    spec = original['specification']
    require(record['source_record_id'] == original['record_id']
            and record['specification'] == spec, 'Original branch or reset schedule differs')
    require(record['original_comparison'] == original.get('comparison')
            and record['original_error'] == original.get('error'), 'Original failure was changed')
    require(spec['stop'] in (1410., 1810., 2210.)
            and original['sample_count'] == round(spec['stop']/.01)+1,
            'Original observation horizon differs')
    require(set(record['integrations']) == set(LABELS), 'Six integration outcomes are required')
    completed = set()
    for label, row in record['integrations'].items():
        engine, level = label.split('_')
        factor = {'original': 1, 'tight': 10, 'tighter': 20}[level]
        expected = {k: float(Decimal(str(v))/factor)
                    for k, v in spec['integration_settings'][engine].items()}
        require(row['request'] == expected, 'Integration request differs from the declared refinement')
        if row['completed'] is True:
            require(row['samples'] == original['sample_count'], 'Observation samples were dropped')
            completed.add(label)
        else:
            require(row['completed'] is False and isinstance(row.get('error'), str) and row['error'],
                    'Incomplete integration requires failure evidence')
    require(set(record['windows']) == completed, 'Window inventory differs from completed integrations')
    for windows in record['windows'].values():
        require(set(windows) == set(trial_windows(round((spec['stop']-1010)/400))),
                'Window horizon differs')
        for rows in windows.values():
            require(set(rows) == set(observables), 'Window observable inventory differs')
            for row in rows.values():
                values = [row[k] for k in ('minimum', 'mean', 'maximum')]
                require(all(math.isfinite(v) for v in values), 'Nonfinite window value')
                slack = 1e-14*max(1., *map(abs, values))
                require(values[0]-slack <= values[1] <= values[2]+slack, 'Invalid window range')
    expected = {a+'_vs_'+b for a, b in PAIRS if a in completed and b in completed}
    require(set(record['comparisons']) == expected, 'Complete comparison inventory is required')
    for comparison in record['comparisons'].values():
        audit_comparison(comparison, original['sample_count'], observables)
    confirmed = REQUIRED <= expected and all(record['comparisons'][k]['passed'] for k in REQUIRED)
    require(record['refinement_confirmed'] is confirmed, 'Refinement outcome contradicts its comparisons')
    return {'record_id': original['record_id'], 'samples': original['sample_count'],
            'completed_integrations': len(completed), 'recorded_refinement_confirmed': confirmed,
            'required_scaled_errors': {k: record['comparisons'][k]['max_scaled_error']
                                      for k in sorted(REQUIRED & expected)}}


def verify(directory, source_report, original_revision, producer_revision):
    directory, source_report = Path(directory), Path(source_report)
    report = read(directory/'report.json')
    require(report['status'] == 'completed', 'Refinement diagnostic is still running')
    original = read(source_report)
    catalog = read(ROOT/'models/catalog.json')['models']
    entry = next(e for e in catalog if e['biomodel_id'] == original['biomodel_id'])
    original_audit = audit_model(source_report.parent, entry, original_revision)
    captured_path = directory/'source-evidence.json'
    captured = read(captured_path)
    require(digest(captured_path) == report['source_evidence_sha256']
            and captured['original_report_sha256'] == digest(source_report)
            and captured['original_report'] == original, 'Captured original report differs')
    archives = {r['file']: r['sha256'] for r in original['evidence_archives']['branches']}
    require(captured['verified_source_archives'] == archives, 'Source archive inventory differs')
    source_branches = read_archives(source_report.parent, original, 'branches')
    failed = {k: v for k, v in source_branches.items() if not v['passed']}
    require(bool(failed) and set(failed) == set(original_audit['failed_branches'])
            and captured['failed_branches'] == [failed[k] for k in sorted(failed)],
            'Complete original failure inventory differs')
    info = inspect_model(ROOT/'models'/(original['biomodel_id']+'.xml'))
    require(original['engines'] == list(ENGINES) and report['model_id'] == original['biomodel_id']
            and report['model_sha256'] == info['sha256'] == original['model_sha256'],
            'Model or engine identity differs')
    require(report['timed_drive_encoding'] == original['configuration'].get('timed_drive_encoding'),
            'Original model encoding differs')
    require(report['script_sha256'] == source_hash(producer_revision, 'scripts/diagnose_breaking_refinement.py'),
            'Diagnostic producer source differs')
    require(set(report['implementation_sha256']) == IMPLEMENTATIONS, 'Implementation inventory differs')
    for name, sha in report['implementation_sha256'].items():
        require(sha == source_hash(producer_revision, 'grn_memory/'+name), 'Implementation source differs: '+name)
    require(set(report['versions']) == set(PACKAGES)
            and all(isinstance(v, str) and v for v in report['versions'].values()),
            'Producer package inventory differs')
    require(report['comparison_settings'] == {'rtol': 2e-5, 'atol': 1e-7}, 'Acceptance thresholds differ')
    config = original['configuration']
    possible = trains_for(pulse_schedule(), {}) + [ResetTrain(t, t+100., {})
                 for t in (1010., 1210., 1410., 1610., 1810., 2010.)]
    grid = sample_times(2210., config['dt'], possible, post_reset_offset=config['post_reset_offset'])
    require(report['observation_grid_sha256'] == hashlib.sha256(grid.tobytes()).hexdigest(),
            'Original observation grid differs')
    rows = report['branches']
    require(report['expected_branches'] == len(failed) == len(rows)
            and {r['record_id'] for r in rows} == set(failed), 'Diagnostic failure coverage is incomplete')
    verified = []
    for row in rows:
        bid = row['record_id']
        require(row['file'] == bid+'.json', 'Unexpected branch path')
        path = directory/row['file']
        require(digest(path) == row['sha256'], 'Branch record digest differs')
        record = read(path)
        result = verify_branch(record, failed[bid], info['observables'])
        require(row['refinement_confirmed'] == result['recorded_refinement_confirmed'],
                'Report summary differs from branch outcome')
        verified.append({**result, 'sha256': row['sha256']})
    count = sum(r['recorded_refinement_confirmed'] for r in verified)
    require(report['confirmed_branches'] == count, 'Confirmed branch count differs')
    return {'purpose': __doc__, 'model_id': original['biomodel_id'],
            'source_report_sha256': digest(source_report), 'report_sha256': digest(directory/'report.json'),
            'verification_script_sha256': digest(Path(__file__)),
            'original_producer_revision': original_revision, 'diagnostic_producer_revision': producer_revision,
            'complete_original_failed_branch_inventory': True, 'branches': verified,
            'completed_integrations': sum(r['completed_integrations'] for r in verified),
            'confirmed_branches': count, 'all_refinements_confirmed': count == len(failed),
            'case_recovery_claimed': False, 'full_model_validation_claimed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--source-report', type=Path, required=True)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--producer-revision', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.input, args.source_report, args.source_revision, args.producer_revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result)
    print(json.dumps({k: result[k] for k in ('model_id', 'confirmed_branches', 'all_refinements_confirmed')}))
