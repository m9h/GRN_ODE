"""Combine the freshly reproduced original Ueda audit with all four recoveries.

The numerical auditors must run first. This final accounting checks that their
case inventories cover the identical full model, without replacing an original
failure or claiming that old and new native trajectories are byte-identical.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def read(path):
    return json.loads(Path(path).read_text())

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()

def main():
    original_path = ROOT/'original-model/BIOMD0000000022.json'
    original_audit_path = ROOT/'original-model/reproduced-audit.json'
    new_audit_path = ROOT/'assembled/audit.json'
    original, audit, recovered = map(read, (original_path, original_audit_path, new_audit_path))
    source = read(ROOT/'assembled/source-evidence.json')
    collection = read(ROOT/'collection/status.json')
    assert digest(original_path) == source['original_report_sha256'] == '26b75b6a08bed830f9e10acc3fb04d647b7cc81df5d46a0e145c42b5a8d1d258'
    assert original == source['original_report']
    assert len(audit['models']) == 1
    model = audit['models'][0]
    assert model['network'] == 11 and model['biomodel_id'] == recovered['model_id'] == 'BIOMD0000000022'
    assert model['report_sha256'] == digest(original_path)
    assert model['complete_initial_case_coverage'] and model['complete_conditional_search']
    assert not model['unresolved_conditional_decisions']
    assert model['cases'] == original['expected_cases'] == original['evaluated_cases'] == 302
    assert model['passed_cases'] == original['passed_cases'] == 298
    assert model['case_summaries'] == original['cases']
    failed = {key for key, value in original['cases'].items() if value['status'] != 'passed'}
    assert failed == set(recovered['cases']) and len(failed) == 4
    assert recovered['selected_cases'] == recovered['recovered_selected_cases'] == 4
    assert recovered['complete_selected_control_inventory'] and recovered['baseline_passed']
    assert not recovered['original_passing_branches_requiring_revalidation']
    assert recovered['report_sha256'] == digest(ROOT/'assembled/report.json')
    assert collection['complete_selected_attempts'] and len(collection['partitions']) == 32
    assert not collection['pending_indices'] and not collection['missing_artifacts'] and not collection['collection_errors']
    branches = recovered['branches']
    assert len(branches) == len({b['record_id'] for b in branches}) == 323
    assert all(b['status'] == 'confirmed' and len(b['traces']) == 4 and len(b['comparisons']) == 6
               and all(c['passed'] for c in b['comparisons'].values()) for b in branches)
    assert all(c['passed'] and c['primary_matches_original_path'] and c['refined_matches_original_path']
               for c in recovered['cases'].values())
    cases = {}
    for key, old in original['cases'].items():
        cases[key] = {'passed': True, 'original_status': old['status'],
                      'original_case_sha256': fingerprint(old),
                      'validation_source': 'original_complete_model_audit'}
        if key in failed:
            cases[key].update(validation_source='complete_independent_control_recovery',
                              recovered_case_sha256=fingerprint(recovered['cases'][key]))
    assert len(cases) == 302 and all(c['passed'] for c in cases.values())
    result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'network': 11,
              'model_id': model['biomodel_id'], 'status': 'passed_with_documented_solver_recovery',
              'expected_cases': 302, 'original_passed_cases': 298, 'original_failed_cases': sorted(failed),
              'recovered_cases': 4, 'combined_passed_cases': 302,
              'complete_initial_case_coverage': True, 'complete_conditional_search': True,
              'whole_model_validation_passed': True, 'cases': cases,
              'recovery_branches': 323, 'recovery_arrays': 1292, 'recovery_pairwise_comparisons': 1938,
              'baseline_passed': True, 'previously_passing_branches_requiring_revalidation': [],
              'original_failures_retained': True, 'cross_run_native_array_agreement_claimed': False,
              'original_report_sha256': digest(original_path),
              'original_reproduced_audit_sha256': digest(original_audit_path),
              'recovery_audit_sha256': digest(new_audit_path),
              'complete_collection_sha256': digest(ROOT/'collection/status.json'),
              'combination_script_sha256': digest(Path(__file__)),
              'numerical_integrations_performed_by_combination': 0,
              'scope': '298 original passing cases freshly reaudited from the published source records, plus all four failed cases recovered from full independent arrays and complete conditional controls. Original numerical failures remain preserved.'}
    output = ROOT/'combined-model-audit.json'
    assert not output.exists(), 'Do not overwrite a published accounting result'
    output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: result[k] for k in ('status','expected_cases','combined_passed_cases','recovered_cases')}))

if __name__ == '__main__':
    main()
