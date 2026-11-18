"""Verify one complete later-control diagnostic from every saved array sample.

This is a branch audit, not a case-recovery or whole-model result. It uses the
unchanged trajectory reader, reset checks, comparisons and window summaries.
"""

from pathlib import Path

from grn_memory.catalog_breaking import trial_windows
from grn_memory.catalog_repeated import summarize
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import comparison
from grn_memory.native_protocols import ResetTrain
from grn_memory.scipy_breaking_recovery import LABELS
from scripts.audit_scipy_breaking import trajectory
from scripts.audit_scipy_breaking_cases import check_outcome
from scripts.run_rohwer_breaking_diagnostics import digest, read, require


def audit(directory, plan, inventory, info, grid, expected_plan_sha):
    from scripts.run_rohwer_later_controls import metadata_for, selected
    directory = Path(directory)
    report_path = directory / 'report.json'
    report_sha = digest(report_path)
    report = read(report_path)
    require(report['status'] == 'completed', 'Later-control diagnostic is still running')
    require(report['metadata'] == metadata_for(plan) and report['plan_sha256'] == expected_plan_sha,
            'Later-control metadata or plan identity differs')
    bid = report['record_id']
    require(bid in {row['record_id'] for row in selected(plan, report['batch_index'], report['partition_index'])},
            'Branch is outside its fixed batch and partition')
    row = report['branch']
    require(row['record_id'] == bid and row['file'] == bid + '.json', 'Branch record path differs')
    path = directory / row['file']
    require(digest(path) == row['sha256'], 'Branch record hash differs')
    record = read(path)
    spec = inventory['branches'][bid]
    require(fingerprint(spec) == bid and record['record_id'] == bid and record['specification'] == spec
            and record['fingerprint'] == report['metadata']['fingerprint']
            and record['case_recovery_claimed'] is False
            and 'reused_from' not in record and 'previous_incomplete_attempts' not in record,
            'Later-control identity, scope or unexpected reuse differs')
    allowed = {'report.json', 'report.json.tmp', 'audit.json', 'audit.json.tmp', bid + '.json', bid + '.tmp'}
    allowed |= {bid + '-' + label + '.npz' for label in LABELS}
    require({p.name for p in directory.iterdir()} <= allowed
            and all(p.is_file() and not p.is_symlink() for p in directory.iterdir()),
            'Unexpected or nonregular later-control evidence')
    require(set(record['integrations']) == set(LABELS), 'Every requested integration outcome is required')
    times = grid[grid <= spec['stop']]
    trains = [ResetTrain(**t) for t in spec['reset_trains']]
    traces = {}
    for label in LABELS:
        outcome = record['integrations'][label]
        if check_outcome(outcome, label, plan['requests'][label], times, info['observables'], trains, info['sha256']):
            require(label in record['traces'], 'Completed integration has no trajectory')
            traces[label] = trajectory(directory, bid, label, record['traces'][label], times, info['observables'])
    require(set(traces) == set(record['traces']), 'Unexpected trajectory outside completed integrations')
    comparisons = {a + '_vs_' + b: comparison(traces[a], traces[b], **plan['acceptance'])
                   for i, a in enumerate(LABELS) for b in LABELS[i+1:] if a in traces and b in traces}
    require(record['comparisons'] == comparisons, 'Saved comparisons do not reproduce from full arrays')
    status = ('incomplete' if len(comparisons) != 6 else
              'confirmed' if all(c['passed'] for c in comparisons.values()) else 'mismatch')
    require(record['status'] == row['status'] == status, 'Later-control status contradicts arrays')
    windows = {label: summarize(trace, trial_windows(round((spec['stop'] - 1010.) / 400.)))
               for label, trace in traces.items()}
    require(digest(report_path) == report_sha, 'Producer report changed during audit')
    return {'model_id': plan['model_id'], 'record_id': bid,
            'batch_index': report['batch_index'], 'partition_index': report['partition_index'],
            'report_sha256': report_sha, 'record_sha256': row['sha256'], 'status': status,
            'complete_requested_outcomes': True, 'verified_arrays': len(traces),
            'samples': len(times), 'traces': record['traces'], 'comparisons': comparisons, 'windows': windows,
            'origin': inventory['branch_origins'][bid],
            'unverified_arrays': sorted(p.name for p in directory.glob('*.npz')
                if p.name not in {bid + '-' + label + '.npz' for label in traces}),
            'unverified_checkpoint_files': sorted(p.name for p in directory.glob('*.tmp')),
            'audit_script_sha256': digest(Path(__file__)),
            'case_recovery_claimed': False, 'full_model_coverage_claimed': False}
