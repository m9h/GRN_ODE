"""Corrupt complete synthetic records to exercise the independent array audit.

The fixture deliberately relabels published Heyoka arrays as mpmath arrays.
It tests auditing only; these temporary records are not simulation evidence.
"""

from copy import deepcopy
import json
import shutil

import numpy as np
import pytest

from grn_memory.catalog_validation import comparison
from grn_memory.catalog_runner import fingerprint
from scripts import audit_marhl_mpmath as auditor


REFERENCE = auditor.ROOT/'results/catalog-paired-taylor-marhl'


def write(path, value):
    path.write_text(json.dumps(value))


def change(path, mutate, resign=False):
    value = json.loads(path.read_text())
    mutate(value)
    if resign:
        value['fingerprint'] = fingerprint({k: value[k] for k in auditor.META_KEYS})
    write(path, value)


@pytest.fixture(scope='module')
def synthetic(tmp_path_factory):
    directory = tmp_path_factory.mktemp('synthetic-mpmath-audit')
    source = json.loads((REFERENCE/'report.json').read_text())
    reference_audit = auditor.audit_reference(REFERENCE)
    report = {'purpose': __doc__, 'model_id': auditor.MODEL, 'model_sha256': auditor.MODEL_SHA256,
              'reference_report_sha256': auditor.digest(REFERENCE/'report.json'),
              'reference_audit_sha256': fingerprint(reference_audit), 'requests': deepcopy(auditor.REQUESTS),
              'acceptance': {'rtol':2e-5, 'atol':1e-7}, 'mpmath_version':'synthetic-test-fixture',
              'numpy_version':'synthetic-test-fixture', 'pandas_version':'synthetic-test-fixture',
              'python':'synthetic-test-fixture',
              'implementation_sha256': {name:auditor.digest(auditor.ROOT/name) for name in auditor.SOURCE_FILES},
              'case_recovery_claimed':False, 'different_integrator_family_claimed':False,
              'status':'completed', 'expected_branches':3, 'branches':[]}
    report['fingerprint'] = fingerprint({k:report[k] for k in auditor.META_KEYS})
    write(directory/'reference-audit.json', reference_audit)
    selections = [('untreated_baseline',source['baseline'])]
    selections.extend((r['branch_id'],r) for r in source['branches'])
    for bid,row in selections:
        path = REFERENCE/row['file']
        original = json.loads(path.read_text())
        record = {'fingerprint':report['fingerprint'], 'branch_id':bid,
                  'reset_trains':original['reset_trains'], 'reference_record_sha256':auditor.digest(path),
                  'reference_traces':original['traces'], 'integrations':{}, 'traces':{}, 'case_recovery_claimed':False}
        with np.load(REFERENCE/original['traces']['taylor192']['file'],allow_pickle=False) as data:
            times = data['times'].copy()
        traces = {k:auditor.trace(REFERENCE,v,bid,k,times) for k,v in original['traces'].items()}
        for label,request in auditor.REQUESTS.items():
            taylor = label.replace('mpmath','taylor')
            output = directory/(bid+'-'+label+'.npz')
            shutil.copyfile(REFERENCE/original['traces'][taylor]['file'],output)
            record['traces'][label] = {'file':output.name,'sha256':auditor.digest(output)}
            record['integrations'][label] = {**original['integrations'][taylor],
                'backend':'mpmath.odefun','mpmath_version':report['mpmath_version'],
                'degree':request['degree'],'rhs_evaluations':1}
            traces[label] = traces[taylor]
        pairs = [('mpmath128','mpmath192')]
        pairs.extend((m,h) for m in auditor.REQUESTS for h in ('taylor128','taylor192','roadrunner'))
        record['comparisons'] = {a+'_vs_'+b:comparison(traces[a],traces[b],**report['acceptance']) for a,b in pairs}
        record['high_precision_agreement'] = True
        record['native_agreement'] = bid == 'untreated_baseline'
        record['status'] = 'high_precision_agreement'
        write(directory/(bid+'.json'),record)
        summary = {'file':bid+'.json','status':record['status']}
        if bid == 'untreated_baseline':
            report['baseline'] = summary
        else:
            report['branches'].append({'branch_id':bid,**summary})
    write(directory/'report.json',report)
    return directory


@pytest.fixture
def editable(synthetic,tmp_path):
    shutil.copytree(synthetic,tmp_path,dirs_exist_ok=True)
    return tmp_path


def first_record(directory):
    return directory/json.loads((directory/'report.json').read_text())['branches'][0]['file']


def test_complete_arrays_keep_native_disagreement_separate(synthetic):
    result = auditor.audit(synthetic)
    assert result['full_protocol_branches'] == result['high_precision_agreeing_branches'] == 3
    assert result['native_agreeing_branches'] == 0 and result['baseline_native_agreement']
    assert result['complete_original_failure_coverage']
    assert not result['case_recovery_claimed'] and not result['different_integrator_family_claimed']
    assert all(r['samples']==30001 and r['resets']==998 for r in result['summaries'][1:])


def test_running_diagnostic_is_not_complete(editable):
    change(editable/'report.json',lambda r:r.update(status='running'))
    with pytest.raises(ValueError,match='still running'):
        auditor.audit(editable)


def test_missing_original_failure_is_rejected(editable):
    change(editable/'report.json',lambda r:r['branches'].pop())
    with pytest.raises(ValueError,match='inventory is incomplete'):
        auditor.audit(editable)


def test_changed_array_is_rejected(editable):
    with (editable/'untreated_baseline-mpmath128.npz').open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(ValueError,match='Trajectory digest differs'):
        auditor.audit(editable)


def test_truncated_array_is_rejected_even_with_updated_checksum(editable):
    path = editable/'untreated_baseline-mpmath128.npz'
    with np.load(path,allow_pickle=False) as data:
        arrays = {key:data[key].copy() for key in data.files}
    arrays['times'] = arrays['times'][:-1]
    arrays['values'] = arrays['values'][:-1]
    np.savez_compressed(path,**arrays)
    change(editable/'untreated_baseline.json',lambda r:r['traces']['mpmath128'].update(sha256=auditor.digest(path)))
    with pytest.raises(ValueError,match='Observation inventory differs'):
        auditor.audit(editable)


@pytest.mark.parametrize('field,value,message',[
    ('performed_resets',997,'Reset or segment coverage'),
    ('absolute_time_preserved',False,'Model, backend or clock'),
    ('degree',16,'Arithmetic precision or degree'),
])
def test_changed_integration_semantics_are_rejected(editable,field,value,message):
    change(first_record(editable),lambda r:r['integrations']['mpmath192'].update({field:value}))
    with pytest.raises(ValueError,match=message):
        auditor.audit(editable)


def test_claimed_native_agreement_cannot_override_saved_arrays(editable):
    change(first_record(editable),lambda r:r['comparisons']['mpmath192_vs_roadrunner'].update(passed=True))
    with pytest.raises(ValueError,match='comparisons do not reproduce'):
        auditor.audit(editable)


@pytest.mark.parametrize('claim',['case_recovery_claimed','different_integrator_family_claimed'])
def test_branch_diagnostic_cannot_be_promoted_to_broader_claim(editable,claim):
    change(editable/'report.json',lambda r:r.update({claim:True}),resign=True)
    with pytest.raises(ValueError,match='cannot claim'):
        auditor.audit(editable)


def test_changed_reference_provenance_is_rejected(editable):
    change(first_record(editable),lambda r:r.update(reference_record_sha256='wrong'))
    with pytest.raises(ValueError,match='Reference branch provenance'):
        auditor.audit(editable)
