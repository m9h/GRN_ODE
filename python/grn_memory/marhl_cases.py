"""Replay every failed Marhl case using independently collected full arrays.

The existing controlled-score mathematics is reused with explicit label aliases:
its four numerical input slots receive Heyoka/mpmath at 128/192 bits. These
aliases do not represent additional RoadRunner or SciPy integrations. Literal
MATLAB search paths and controlled classifications remain separate outputs.
"""
from pathlib import Path
import hashlib
import subprocess

from . import marhl_collection as collector, marhl_precision as work
from .marhl_precision import digest, read, require, write_json
from scripts import audit_scipy_breaking_cases as scores
from scripts import prepare_marhl_full_controls as inputs

LABELS = {'roadrunner': 'taylor128', 'roadrunner_refined': 'taylor192',
          'scipy': 'mpmath128', 'scipy_refined': 'mpmath192'}


def rename(value):
    if isinstance(value, dict):
        return {LABELS.get(key, key): rename(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rename(item) for item in value]
    if isinstance(value, str):
        return LABELS.get(value, value)
    return value


def evaluate_case(plan, reference, config, branches, baseline):
    """Use the unchanged original search and score rules, including zero cases."""
    aliases = {bid: {'status': row['status'], 'windows': {
        old: row['windows'][new] for old, new in LABELS.items() if new in row['windows']}}
        for bid, row in branches.items()}
    return rename(scores.evaluate_case(plan, reference, config, aliases, baseline))


def original_context():
    plan, inventory = collector.context()
    original_score_source = subprocess.check_output(['git', 'show', collector.PRODUCER+
        ':python/scripts/audit_scipy_breaking_cases.py'], cwd=work.ROOT)
    require(hashlib.sha256(original_score_source).hexdigest() == digest(scores.__file__),
            'Original controlled-score and conditional-search implementation differs')
    validation = inputs.check(collector.cloud.INVENTORY)
    reference = read(work.ROOT/'results/catalog-repeated'/f'{inputs.MODEL}.json')
    reports, records, originals = [], [], {}
    for index in range(4):
        directory = inputs.SOURCE/f'shard-{index}'
        report = read(directory/f'{inputs.MODEL}.json')
        reports.append(report)
        records.append(inputs.read_archives(directory, report, 'branches'))
        for record in inputs.read_archives(directory, report, 'cases').values():
            key = record['case_key']
            if key in inventory['cases']:
                require(key not in originals, 'Duplicate original selected case')
                originals[key] = record
    require(set(originals) == set(inventory['cases']) and len(originals) == 12,
            'Every original failed case record is required')
    return plan, inventory, reference, reports[0]['configuration'], originals, records, validation


def replay(inventory, branches, reference, config, originals):
    require(set(branches) == set(inventory['branches']) and set(originals) == set(inventory['cases']),
            'Every original branch and selected case must remain in scope')
    baseline = branches[inventory['full_untreated_control']]['status'] == 'confirmed'
    cases = {}
    for key, case in inventory['cases'].items():
        result = evaluate_case(case['original_plan'], reference, config, branches, baseline)
        original_path = {name: {field: trial[field] for field in ('breakers', 'responses')}
                         for name, trial in originals[key]['trials'].items()}
        result['original_path'] = original_path
        for label in ('primary', 'refined'):
            path = {name: {field: trial[field] for field in ('breakers', 'responses')}
                    for name, trial in result[label+'_search']['trials'].items()}
            result[label+'_matches_original_path'] = path == original_path
        cases[key] = result
    return baseline, cases


def audit(selection, snapshots, archives, output):
    """Reauthenticate original archives and recompute arrays before case scoring."""
    output = Path(output)
    require(not output.exists() and not output.is_symlink(), 'Use a new complete-case audit directory')
    protected = [Path(snapshots).resolve(), Path(archives).resolve()]
    require(not any(output.resolve().is_relative_to(p) for p in protected), 'Audit must not modify input evidence')
    plan, inventory, reference, config, originals, old_branches, validation = original_context()
    collection = collector.collect(selection, snapshots, archives, output/'collection')
    branches = {bid: {'status': 'pending', 'windows': {}} for bid in plan['branches']}
    for entry in collection['branches']:
        if 'file' not in entry:
            continue
        path = output/'collection'/entry['file']
        require(digest(collector.regular(path)) == entry['sha256'], 'Fresh independent branch audit changed')
        row = read(path)
        require(row['branch_id'] == entry['branch_id'] and row['status'] == entry['status'], 'Branch audit identity differs')
        branches[row['branch_id']] = {'status': 'confirmed' if row['status'] == 'agreement' else row['status'],
                                     'windows': row['windows']}
    baseline, cases = replay(inventory, branches, reference, config, originals)
    discrepancies = []
    for partition, rows in enumerate(old_branches):
        for bid, old in rows.items():
            if bid in branches and old['passed'] and branches[bid]['status'] == 'confirmed':
                difference = scores.summary_discrepancy(old, branches[bid])
                if difference['max_scaled_error'] > 1:
                    discrepancies.append({'partition': partition, 'branch_id': bid, **difference})
    complete = collection['all_required_arrays_verified'] and len(cases) == 12
    result = {'schema': 1, 'checked_at': work.now(), 'model_id': inventory['model_id'],
              'plan_sha256': collector.PLAN_SHA, 'inventory_sha256': work.INVENTORY_SHA256,
              'selection_sha256': digest(selection), 'original_input_validation': validation,
              'required_tasks': 1520, 'required_branches': 380, 'required_selected_cases': 12,
              'original_model_cases': 38, 'original_passing_cases': 26, 'historical_passing_cases_not_rerun': 26,
              'baseline_passed': baseline, 'cases': cases, 'selected_cases_passed': sum(c['passed'] for c in cases.values()),
              'complete_selected_array_coverage': complete, 'historical_window_contradictions': discrepancies,
              'selected_case_validation_passed': complete and not discrepancies and all(c['passed'] for c in cases.values()),
              'controlled_score_input_aliases': LABELS, 'different_integrator_family_claimed': False,
              'numerical_integrations_performed': 0, 'full_model_coverage_claimed': False,
              'collection_sha256': digest(output/'collection/collection.json'),
              'auditor_sha256': digest(__file__), 'score_source_sha256': digest(scores.__file__)}
    write_json(output/'audit.json', result)
    return result
