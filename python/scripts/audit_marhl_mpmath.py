"""Audit every saved sample of the independent Marhl implementation diagnostic.

No integration is rerun. Precision agreement, native agreement and complete
case validation are separate claims; this branch diagnostic cannot recover cases.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from grn_memory.breaking_audit import require
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import comparison
from grn_memory.native_protocols import ResetTrain, sample_times
from scripts.audit_taylor_paired import audit as audit_reference


MODEL = 'BIOMD0000000039'
MODEL_SHA256 = '6b221222be03747b11454cc4f2a6218697d9c6367d3578a170c7cc5c34ad3b12'
NAMES = ['Ca_cyt', 'CaER', 'CaM', 'CaPr', 'Pr']
REQUESTS = {'mpmath128': {'precision': 128, 'tolerance': '1e-30', 'degree': 32},
            'mpmath192': {'precision': 192, 'tolerance': '1e-45', 'degree': 48}}
META_KEYS = ('model_id', 'model_sha256', 'reference_report_sha256', 'reference_audit_sha256',
             'requests', 'acceptance', 'mpmath_version', 'numpy_version', 'pandas_version',
             'python', 'implementation_sha256', 'case_recovery_claimed', 'different_integrator_family_claimed')
SOURCE_FILES = {'grn_memory/marhl_mpmath.py', 'grn_memory/catalog_validation.py',
                'scripts/diagnose_marhl_mpmath.py'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trace(directory, saved, bid, label, times):
    require(saved['file'] == bid+'-'+label+'.npz', 'Unexpected trajectory path')
    path = directory/saved['file']
    require(digest(path) == saved['sha256'], 'Trajectory digest differs')
    with np.load(path, allow_pickle=False) as data:
        require(list(data['observables']) == NAMES and np.array_equal(data['times'], times),
                'Observation inventory differs')
        values = data['values']
        require(values.shape == (len(times), len(NAMES)) and np.isfinite(values).all(),
                'Incomplete trajectory array')
        result = pd.DataFrame(values, columns=NAMES)
        result.insert(0, 'time', times)
    return result


def audit(directory, reference=None):
    directory = Path(directory)
    reference = ROOT/'results/catalog-paired-taylor-marhl' if reference is None else Path(reference)
    report_path = directory/'report.json'
    report = json.loads(report_path.read_text())
    require(report['status'] == 'completed', 'Diagnostic is still running')
    require(fingerprint({k: report[k] for k in META_KEYS}) == report['fingerprint'],
            'Diagnostic fingerprint differs')
    require(report['model_id'] == MODEL and report['model_sha256'] == MODEL_SHA256
            and digest(ROOT/'models'/(MODEL+'.xml')) == MODEL_SHA256, 'Model source differs')
    require(report['requests'] == REQUESTS and report['acceptance'] == {'rtol': 2e-5, 'atol': 1e-7},
            'Precision requests or acceptance threshold differ')
    require(report['case_recovery_claimed'] is False and report['different_integrator_family_claimed'] is False,
            'A Taylor branch diagnostic cannot claim case recovery or different integrator families')
    require(set(report['implementation_sha256']) == SOURCE_FILES, 'Implementation inventory differs')
    for name, sha in report['implementation_sha256'].items():
        require(digest(ROOT/name) == sha, 'Implementation source differs: '+name)
    reference_result = audit_reference(reference)
    require(report['reference_report_sha256'] == digest(reference/'report.json')
            and report['reference_audit_sha256'] == fingerprint(reference_result), 'Reference provenance differs')
    require(json.loads((directory/'reference-audit.json').read_text()) == reference_result,
            'Saved reference audit differs')
    source = json.loads((reference/'report.json').read_text())
    originals = {row['branch_id']: row for row in source['branches']}
    require(source['model_id'] == MODEL and report['expected_branches'] == len(originals) == 3,
            'Original failure inventory differs')
    require(len(report['branches']) == 3 and {r['branch_id'] for r in report['branches']} == set(originals),
            'Original failure inventory is incomplete')
    grid = sample_times(300., .01, [ResetTrain(t, t+50., {}) for t in (50., 150., 200.)], post_reset_offset=1e-5)
    selections = [('untreated_baseline', report['baseline'], source['baseline'], grid[grid <= 50.])]
    selections.extend((row['branch_id'], row, originals[row['branch_id']], grid) for row in report['branches'])
    summaries = []
    for bid, row, original_row, times in selections:
        require(row['file'] == bid+'.json', 'Unexpected branch evidence path')
        path = directory/row['file']
        record = json.loads(path.read_text())
        original_path = reference/original_row['file']
        original = json.loads(original_path.read_text())
        require(record['fingerprint'] == report['fingerprint'] and record['branch_id'] == bid, 'Branch identity differs')
        require(record['reference_record_sha256'] == digest(original_path)
                and record['reference_traces'] == original['traces'], 'Reference branch provenance differs')
        trains = original['reset_trains']
        require(record['reset_trains'] == trains, 'Original reset schedule differs')
        counts = [len(ResetTrain(**t).indices()) if t['values'] else 0 for t in trains]
        reset_times = sorted({float(v) for t in trains if t['values'] for v in ResetTrain(**t).times()})
        resets = len(reset_times)
        require(set(record['integrations']) == set(record['traces']) == set(REQUESTS),
                'Both complete arbitrary-precision integrations are required')
        traces = {label: trace(reference, saved, bid, label, times) for label, saved in original['traces'].items()}
        for label, request in REQUESTS.items():
            traces[label] = trace(directory, record['traces'][label], bid, label, times)
            evidence = record['integrations'][label]
            require(evidence['completed'] is True and evidence['sample_count'] == len(times)
                    and evidence['observables'] == NAMES, 'Integration outcome differs')
            require(evidence['backend'] == 'mpmath.odefun' and evidence['mpmath_version'] == report['mpmath_version']
                    and evidence['model_sha256'] == MODEL_SHA256 and evidence['absolute_time_preserved'] is True
                    and evidence['numeric_inputs'] == 'binary64 values promoted exactly', 'Model, backend or clock differs')
            require(evidence['precision_bits'] == request['precision'] and evidence['degree'] == request['degree']
                    and float(evidence['tolerance']) == float(request['tolerance']), 'Arithmetic precision or degree differs')
            require(evidence['expected_resets'] == evidence['performed_resets'] == resets
                    and evidence['expected_train_reset_counts'] == evidence['train_reset_counts'] == counts
                    and evidence['expected_segments'] == evidence['completed_segments'] == resets+1
                    and evidence['last_interval'] == [reset_times[-1] if resets else 0., float(times[-1])]
                    and evidence['rhs_evaluations'] > 0, 'Reset or segment coverage is incomplete')
        pairs = [('mpmath128', 'mpmath192')]
        pairs.extend((m, h) for m in REQUESTS for h in ('taylor128', 'taylor192', 'roadrunner'))
        comparisons = {a+'_vs_'+b: comparison(traces[a], traces[b], **report['acceptance']) for a, b in pairs}
        require(record['comparisons'] == comparisons, 'Saved pointwise comparisons do not reproduce')
        high = all(c['passed'] for name, c in comparisons.items() if not name.endswith('_vs_roadrunner'))
        native = all(c['passed'] for name, c in comparisons.items() if name.endswith('_vs_roadrunner'))
        status = 'high_precision_agreement' if high else 'mismatch'
        require(record['high_precision_agreement'] == high and record['native_agreement'] == native
                and record['status'] == row['status'] == status and record['case_recovery_claimed'] is False,
                'Diagnostic outcome differs')
        summaries.append({'branch_id': bid, 'status': status, 'high_precision_agreement': high,
                          'native_agreement': native, 'samples': len(times), 'resets': resets,
                          'record_sha256': digest(path), 'trajectory_sha256': {k: v['sha256'] for k, v in record['traces'].items()},
                          'comparisons': comparisons})
    return {'purpose': __doc__, 'report_sha256': digest(report_path), 'model_id': MODEL,
            'complete_original_failure_coverage': True, 'full_protocol_branches': 3,
            'high_precision_agreeing_branches': sum(s['high_precision_agreement'] for s in summaries[1:]),
            'native_agreeing_branches': sum(s['native_agreement'] for s in summaries[1:]),
            'baseline_status': summaries[0]['status'], 'baseline_native_agreement': summaries[0]['native_agreement'],
            'case_recovery_claimed': False, 'different_integrator_family_claimed': False,
            'summaries': summaries, 'audit_script_sha256': digest(Path(__file__))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--reference', type=Path, default=ROOT/'results/catalog-paired-taylor-marhl')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.input, args.reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result)
    print(json.dumps({k: result[k] for k in ('model_id', 'full_protocol_branches',
          'high_precision_agreeing_branches', 'native_agreeing_branches', 'baseline_status')}))
