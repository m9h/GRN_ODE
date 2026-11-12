"""Exercise complete-case auditing with explicitly synthetic temporary data.

Copied Heyoka arrays are relabelled as mpmath results, and control arrays are
invented constants. These fixtures test the audit and are not model results.
"""

from copy import deepcopy
import json
import shutil

import numpy as np
import pytest

from scripts import audit_marhl_cases as auditor
from scripts import audit_marhl_mpmath as failed_auditor
from scripts.diagnose_marhl_controls import prepare_plan


REFERENCE = auditor.ROOT/'results/catalog-paired-taylor-marhl'


def write(path,value):
    path.write_text(json.dumps(value))


def change(path,mutate):
    value = auditor.read(path);mutate(value);write(path,value)


@pytest.fixture(scope='module')
def synthetic(tmp_path_factory):
    root = tmp_path_factory.mktemp('synthetic-marhl-complete-cases')
    mp,controls = root/'mpmath',root/'controls'
    mp.mkdir();controls.mkdir()
    ref = auditor.read(REFERENCE/'report.json')
    ref_audit = failed_auditor.audit_reference(REFERENCE)
    versions = {**ref['versions'],'mpmath':'synthetic-test-fixture'}
    mp_report = {'purpose':__doc__,'model_id':auditor.MODEL,'model_sha256':auditor.MODEL_SHA256,
                 'reference_report_sha256':auditor.digest(REFERENCE/'report.json'),
                 'reference_audit_sha256':auditor.fingerprint(ref_audit),
                 'requests':deepcopy(failed_auditor.REQUESTS),'acceptance':auditor.ACCEPTANCE,
                 'mpmath_version':versions['mpmath'],'numpy_version':versions['numpy'],
                 'pandas_version':versions['pandas'],'python':ref['python'],
                 'implementation_sha256':{n:auditor.digest(auditor.ROOT/n) for n in failed_auditor.SOURCE_FILES},
                 'case_recovery_claimed':False,'different_integrator_family_claimed':False,
                 'status':'completed','expected_branches':3,'branches':[]}
    mp_report['fingerprint'] = auditor.fingerprint({k:mp_report[k] for k in failed_auditor.META_KEYS})
    write(mp/'reference-audit.json',ref_audit)
    selections = [('untreated_baseline',ref['baseline'])]+[(r['branch_id'],r) for r in ref['branches']]
    for bid,row in selections:
        path = REFERENCE/row['file'];original = auditor.read(path)
        record = {'branch_id':bid,'fingerprint':mp_report['fingerprint'],'reset_trains':original['reset_trains'],
                  'reference_record_sha256':auditor.digest(path),'reference_traces':original['traces'],
                  'integrations':{},'traces':{},'case_recovery_claimed':False}
        with np.load(REFERENCE/original['traces']['taylor192']['file'],allow_pickle=False) as data:
            times = data['times'].copy()
        traces = {k:auditor.trace(REFERENCE,v,bid,k,times) for k,v in original['traces'].items()}
        for label,request in failed_auditor.REQUESTS.items():
            taylor = label.replace('mpmath','taylor');out = mp/(bid+'-'+label+'.npz')
            shutil.copyfile(REFERENCE/original['traces'][taylor]['file'],out)
            record['traces'][label] = {'file':out.name,'sha256':auditor.digest(out)}
            record['integrations'][label] = {**original['integrations'][taylor],
                'backend':'mpmath.odefun','mpmath_version':versions['mpmath'],'degree':request['degree'],'rhs_evaluations':1}
            traces[label] = traces[taylor]
        pairs = [('mpmath128','mpmath192')]+[(m,h) for m in failed_auditor.REQUESTS
                                                       for h in ('taylor128','taylor192','roadrunner')]
        record['comparisons'] = {a+'_vs_'+b:auditor.comparison(traces[a],traces[b],**auditor.ACCEPTANCE) for a,b in pairs}
        record.update(high_precision_agreement=True,native_agreement=bid=='untreated_baseline',status='high_precision_agreement')
        write(mp/(bid+'.json'),record)
        summary = {'file':bid+'.json','status':record['status']}
        if bid=='untreated_baseline':mp_report['baseline']=summary
        else:mp_report['branches'].append({'branch_id':bid,**summary})
    write(mp/'report.json',mp_report)
    plan = prepare_plan();write(controls/'plan.json',plan)
    grid = auditor.sample_times(300.,.01,[auditor.ResetTrain(t,t+50.,{}) for t in (50.,150.,200.)],post_reset_offset=1e-5)
    report = {'purpose':__doc__,'plan_sha256':auditor.fingerprint(plan),'requests':auditor.REQUESTS,
              'acceptance':auditor.ACCEPTANCE,'sample_grid_sha256':auditor.hashlib.sha256(grid.tobytes()).hexdigest(),
              'samples':len(grid),'implementation_sha256':{n:auditor.digest(auditor.ROOT/n) for n in auditor.SOURCES},
              'versions':versions,'python':ref['python'],'case_recovery_claimed':False,
              'different_integrator_family_claimed':False,'status':'completed','expected_branches':15,
              'selected_branch_ids':plan['selected_branch_ids'],'branches':[]}
    report['fingerprint'] = auditor.fingerprint({k:report[k] for k in auditor.META_KEYS})
    template = auditor.read(REFERENCE/'untreated_baseline.json')
    for index,bid in enumerate(plan['selected_branch_ids']):
        original = plan['selected_branches'][bid];trains = original['reset_trains']
        counts = [len(auditor.ResetTrain(**t).indices()) if t['values'] else 0 for t in trains]
        resets = sorted({float(v) for t in trains if t['values'] for v in auditor.ResetTrain(**t).times()})
        record = {'branch_id':bid,'fingerprint':report['fingerprint'],'reset_trains':trains,
                  'specification':original['specification'],'case_recovery_claimed':False,'integrations':{},'traces':{}}
        values = np.full((len(grid),len(auditor.NAMES)),1.+.1*index)
        traces = {}
        for label,request in auditor.REQUESTS.items():
            evidence = {'request':request,'completed':True,'sample_count':len(grid),'observables':auditor.NAMES}
            if label!='roadrunner':
                taylor = label.replace('mpmath','taylor')
                evidence.update(template['integrations'][taylor])
                evidence.update(sample_count=len(grid),expected_resets=len(resets),performed_resets=len(resets),
                                expected_train_reset_counts=counts,train_reset_counts=counts,
                                expected_segments=len(resets)+1,completed_segments=len(resets)+1,
                                last_interval=[resets[-1] if resets else 0.,300.])
                if label.startswith('mpmath'):
                    evidence.update(backend='mpmath.odefun',mpmath_version=versions['mpmath'],degree=request['degree'],rhs_evaluations=1)
            out = controls/(bid+'-'+label+'.npz')
            np.savez_compressed(out,times=grid,values=values,observables=np.asarray(auditor.NAMES))
            record['integrations'][label]=evidence
            record['traces'][label]={'file':out.name,'sha256':auditor.digest(out)}
            traces[label]=auditor.trace(controls,record['traces'][label],bid,label,grid)
        record.update(comparisons=auditor.comparisons(traces),high_precision_agreement=True,
                      native_agreement=True,status='high_precision_agreement')
        write(controls/(bid+'.json'),record)
        report['branches'].append({'branch_id':bid,'file':bid+'.json','status':record['status']})
    write(controls/'report.json',report)
    return root


@pytest.fixture
def editable(synthetic,tmp_path):
    shutil.copytree(synthetic,tmp_path,dirs_exist_ok=True)
    return tmp_path


def run(directory):
    return auditor.audit(directory/'controls',directory/'mpmath')


def first_record(directory):
    controls = directory/'controls'
    return controls/auditor.read(controls/'report.json')['branches'][0]['file']


def test_complete_synthetic_evidence_scores_every_arm(synthetic):
    result = run(synthetic)
    assert result['required_branch_count']==result['high_precision_agreeing_branches']==18
    assert result['native_agreeing_branches']==15
    assert result['original_passed_cases']==24 and result['recovered_cases']==2
    assert result['combined_passed_cases']==26 and result['all_cases_validated']
    assert not result['different_integrator_family_claimed']
    assert all(len(c['branches'])==12 and set(c['scores'])=={'taylor192','mpmath192'} for c in result['cases'].values())


@pytest.mark.parametrize('mutation,message',[
    (lambda r:r.update(status='running'),'still running'),
    (lambda r:r['branches'].pop(),'branch inventory'),
])
def test_incomplete_controls_cannot_recover_cases(editable,mutation,message):
    change(editable/'controls/report.json',mutation)
    with pytest.raises(ValueError,match=message):run(editable)


def test_incomplete_case_plan_is_rejected(editable):
    change(editable/'controls/plan.json',lambda p:next(iter(p['cases'].values()))['branches'].pop('none_sham'))
    with pytest.raises(ValueError,match='case plan'):run(editable)


def test_changed_environment_cannot_mix_case_arms(editable):
    def mutate(report):
        report['versions']['heyoka']='different'
        report['fingerprint']=auditor.fingerprint({k:report[k] for k in auditor.META_KEYS})
    change(editable/'controls/report.json',mutate)
    with pytest.raises(ValueError,match='producer environments'):run(editable)


@pytest.mark.parametrize('field,value,message',[
    ('performed_resets',0,'Reset or segment'),
    ('degree',16,'implementation settings'),
    ('absolute_time_preserved',False,'Model or clock'),
])
def test_invalid_control_integration_is_rejected(editable,field,value,message):
    change(first_record(editable),lambda r:r['integrations']['mpmath192'].update({field:value}))
    with pytest.raises(ValueError,match=message):run(editable)


def test_truncated_array_is_rejected_with_updated_checksum(editable):
    record_path=first_record(editable);record=auditor.read(record_path)
    path=record_path.parent/record['traces']['mpmath192']['file']
    with np.load(path,allow_pickle=False) as data:arrays={k:data[k].copy() for k in data.files}
    arrays['values']=arrays['values'][:-1];arrays['times']=arrays['times'][:-1]
    np.savez_compressed(path,**arrays)
    change(record_path,lambda r:r['traces']['mpmath192'].update(sha256=auditor.digest(path)))
    with pytest.raises(ValueError,match='Observation inventory'):run(editable)


def test_claimed_comparison_cannot_override_arrays(editable):
    change(first_record(editable),lambda r:r['comparisons']['mpmath128_vs_mpmath192'].update(max_scaled_error=1.))
    with pytest.raises(ValueError,match='comparisons do not reproduce'):run(editable)


def test_self_consistent_failed_control_cannot_recover_cases(editable):
    controls=editable/'controls';plan=auditor.read(controls/'plan.json')
    bid=next(iter(plan['cases'].values()))['branches']['none_sham']
    record_path=controls/(bid+'.json');record=auditor.read(record_path)
    path=controls/record['traces']['mpmath192']['file']
    with np.load(path,allow_pickle=False) as data:arrays={k:data[k].copy() for k in data.files}
    arrays['values']*=2.
    np.savez_compressed(path,**arrays)
    record['traces']['mpmath192']['sha256']=auditor.digest(path)
    traces={k:auditor.trace(controls,v,bid,k,arrays['times']) for k,v in record['traces'].items()}
    record['comparisons']=auditor.comparisons(traces)
    record.update(high_precision_agreement=False,native_agreement=False,status='mismatch')
    write(record_path,record)
    def update_summary(report):
        next(r for r in report['branches'] if r['branch_id']==bid)['status']='mismatch'
    change(controls/'report.json',update_summary)
    result=run(editable)
    assert result['high_precision_agreeing_branches']==17
    assert result['recovered_cases']==0 and result['combined_passed_cases']==24
    assert all('none_sham' in c['unconfirmed_branches'] for c in result['cases'].values())


def test_baseline_mismatch_prevents_case_promotion(synthetic):
    result=run(synthetic)
    rescored=auditor.score_cases(result['cases'],result['branches'],False)
    assert all(c['status']=='failed' for c in rescored.values())


def test_controlled_score_disagreement_blocks_passing_trajectories():
    roles={h+'_'+p:h+'_'+p for h in ('none','ucs','cs','paired') for p in ('sham','normal','delayed')}
    branches={bid:{'high_precision_agreement':True,'native_agreement':True,
                  'windows':{e:{w:{'Ca_cyt':{'mean':1.,'minimum':1.,'maximum':1.}} for w in auditor.WINDOWS}
                             for e in auditor.ENGINES}} for bid in roles.values()}
    # The means differ by only 2e-8, inside the pointwise tolerance, but straddle
    # the cue contrast's numerical-resolution boundary.
    boundary=4.02e-5/(1.-2e-5)
    for engine,shift in zip(auditor.ENGINES,(-1e-8,1e-8)):
        value=1.+boundary+shift
        branches['paired_normal']['windows'][engine]['probe']['Ca_cyt']={k:value for k in ('mean','minimum','maximum')}
    cases={'synthetic':{'ucs':'synthetic','cs':'synthetic','responses':['Ca_cyt'],'branches':roles}}
    result=auditor.score_cases(cases,branches,True)['synthetic']
    assert result['status']=='failed' and not result['unconfirmed_branches']
    assert result['controlled_classification_disagreements']==['Ca_cyt']
