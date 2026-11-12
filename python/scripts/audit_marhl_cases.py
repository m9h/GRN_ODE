"""Recompute complete Marhl cases from all saved high-precision trajectories.

Every arm uses the same two 192-bit implementations, with both 128-bit
refinements checked. Native disagreement remains explicit. Both independent
implementations use Taylor methods; no different-family agreement is claimed.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from grn_memory.breaking_audit import require
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_paired import WINDOWS
from grn_memory.catalog_repeated import summarize
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import comparison
from grn_memory.native_protocols import ResetTrain, sample_times
from grn_memory.paired_scores import classification_key, response_score
from scripts.audit_marhl_mpmath import (MODEL, MODEL_SHA256, NAMES, digest, trace,
                                       audit as audit_failed_branches)
from scripts.recover_scipy_paired_cases import original_context


REVISION = '70a3afad61357e94873ff62a7300c099b4c7ae3e'
REQUESTS = {'taylor128': {'precision':128, 'tolerance':'1e-30'},
            'taylor192': {'precision':192, 'tolerance':'1e-45'},
            'mpmath128': {'precision':128, 'tolerance':'1e-30', 'degree':32},
            'mpmath192': {'precision':192, 'tolerance':'1e-45', 'degree':48},
            'roadrunner': {'rtol':1e-13, 'atol':1e-15}}
ENGINES = ('taylor192', 'mpmath192')
ACCEPTANCE = {'rtol':2e-5, 'atol':1e-7}
META_KEYS = ('plan_sha256', 'requests', 'acceptance', 'sample_grid_sha256', 'samples',
             'implementation_sha256', 'versions', 'python', 'case_recovery_claimed',
             'different_integrator_family_claimed')
SOURCES = {'scripts/diagnose_marhl_controls.py', 'scripts/recover_scipy_paired_cases.py',
           'grn_memory/marhl_mpmath.py', 'grn_memory/taylor_reference.py',
           'grn_memory/native_protocols.py', 'grn_memory/catalog_validation.py'}


def read(path):
    return json.loads(path.read_text())


def comparisons(traces):
    labels = list(REQUESTS)
    return {a+'_vs_'+b:comparison(traces[a],traces[b],**ACCEPTANCE)
            for i,a in enumerate(labels) for b in labels[i+1:]}


def agreement(values):
    high = [v['passed'] for k,v in values.items() if not k.endswith('_vs_roadrunner')]
    native = [v['passed'] for k,v in values.items() if k.endswith('_vs_roadrunner')]
    require(len(high)==6 and len(native)==4, 'Complete comparison inventory is required')
    return all(high), all(native)


def validate_integration(label, evidence, trains, report):
    require(evidence['request']==REQUESTS[label] and evidence['completed'] is True
            and evidence['sample_count']==30001 and evidence['observables']==NAMES,
            'Complete integration observations and requests are required')
    if label=='roadrunner':
        return
    counts = [len(ResetTrain(**t).indices()) if t['values'] else 0 for t in trains]
    resets = sorted({float(v) for t in trains if t['values'] for v in ResetTrain(**t).times()})
    request = REQUESTS[label]
    require(evidence['model_sha256']==MODEL_SHA256 and evidence['absolute_time_preserved'] is True
            and evidence['numeric_inputs']=='binary64 values promoted exactly', 'Model or clock differs')
    require(evidence['precision_bits']==request['precision']
            and float(evidence['tolerance'])==float(request['tolerance']), 'Precision request differs')
    require(evidence['expected_resets']==evidence['performed_resets']==len(resets)
            and evidence['expected_train_reset_counts']==evidence['train_reset_counts']==counts
            and evidence['expected_segments']==evidence['completed_segments']==len(resets)+1
            and evidence['last_interval']==[resets[-1] if resets else 0.,300.],
            'Reset or segment coverage is incomplete')
    if label.startswith('mpmath'):
        require(evidence['backend']=='mpmath.odefun' and evidence['degree']==request['degree']
                and evidence['mpmath_version']==report['versions']['mpmath']
                and evidence['rhs_evaluations']>0, 'mpmath implementation settings differ')
    else:
        require(evidence['high_accuracy'] is True and evidence['integration_steps']>0,
                'Heyoka integration settings differ')


def validate_controls_metadata(directory, plan, reference_report, mpmath_report, grid):
    report = read(directory/'report.json')
    require(report['status']=='completed', 'Control diagnostic is still running')
    require(fingerprint({k:report[k] for k in META_KEYS})==report['fingerprint'],
            'Control fingerprint differs')
    require(read(directory/'plan.json')==plan and report['plan_sha256']==fingerprint(plan),
            'Complete original case plan differs')
    require(report['requests']==REQUESTS and report['acceptance']==ACCEPTANCE,
            'Integration requests or acceptance threshold differ')
    require(report['samples']==len(grid)==30001
            and report['sample_grid_sha256']==hashlib.sha256(grid.tobytes()).hexdigest(),
            'Original sample grid differs')
    require(report['case_recovery_claimed'] is False and report['different_integrator_family_claimed'] is False,
            'Producer cannot claim complete case recovery or different integrator families')
    require(set(report['implementation_sha256'])==SOURCES, 'Implementation inventory differs')
    for name,sha in report['implementation_sha256'].items():
        require(digest(ROOT/name)==sha, 'Control implementation source differs: '+name)
    versions = report['versions']
    require(set(versions)=={'heyoka','mpmath','numpy','pandas','libroadrunner','python-libsbml'},
            'Control environment inventory differs')
    require(reference_report['requests']=={k:REQUESTS[k] for k in ('taylor128','taylor192')}
            and reference_report['native_request']==REQUESTS['roadrunner'],
            'Reference integration requests differ')
    require(all(versions[p]==v for p,v in reference_report['versions'].items())
            and all(versions[p]==mpmath_report[p+'_version'] for p in ('mpmath','numpy','pandas'))
            and report['python']==reference_report['python']==mpmath_report['python'],
            'Cannot mix producer environments across case arms')
    selected = plan['selected_branch_ids']
    require(report['selected_branch_ids']==selected and report['expected_branches']==len(selected)==15
            and len(report['branches'])==15 and {r['branch_id'] for r in report['branches']}==set(selected),
            'Complete control branch inventory is required')
    return report


def score_cases(cases, branches, baseline_passed):
    result = {}
    for key,case in cases.items():
        ids = case['branches']
        require(len(ids)==12 and set(ids)=={h+'_'+p for h in ('none','ucs','cs','paired')
                                           for p in ('sham','normal','delayed')},
                'All twelve original case arms are required')
        require(set(ids.values())<=branches.keys(), 'Required case branch is missing')
        cells = {role:branches[bid] for role,bid in ids.items()}
        scores = {e:{r:response_score(cells,e,r) for r in case['responses']} for e in ENGINES}
        disagreements = [r for r in case['responses'] if
                         classification_key(scores[ENGINES[0]][r])!=classification_key(scores[ENGINES[1]][r])]
        paper = {r:[k for k,v in scores[ENGINES[0]][r]['paper_like'].items()
                    if v!=scores[ENGINES[1]][r]['paper_like'][k]] for r in case['responses']}
        unconfirmed = {role:bid for role,bid in ids.items() if not branches[bid]['high_precision_agreement']}
        result[key] = {**case,'original_status':'failed','scores':scores,
                       'unconfirmed_branches':unconfirmed,'baseline_passed':baseline_passed,
                       'controlled_classification_disagreements':disagreements,
                       'paper_like_disagreements':{r:v for r,v in paper.items() if v},
                       'native_disagreeing_branches':{role:bid for role,bid in ids.items()
                                                      if not branches[bid]['native_agreement']},
                       'status':'passed' if baseline_passed and not unconfirmed and not disagreements else 'failed'}
    return result


def original_cases_requiring_revalidation(original_cases, branches):
    """Do not carry forward a pass contradicted by newly checked shared arms."""
    affected = {}
    for key,case in original_cases.items():
        if case['status']!='passed':
            continue
        conflicts = {}
        for role,bid in case['branches'].items():
            if bid not in branches:
                continue
            branch = branches[bid]
            reasons = []
            if not branch['high_precision_agreement']:reasons.append('precision_refinement_unresolved')
            if not branch['native_agreement']:reasons.append('refined_native_disagreement')
            if reasons:conflicts[role] = {'branch_id':bid,'reasons':reasons}
        if conflicts:affected[key] = conflicts
    return affected


def audit(controls, mpmath, reference=None, original_directory=None):
    controls,mpmath = Path(controls),Path(mpmath)
    reference = ROOT/'results/catalog-paired-taylor-marhl' if reference is None else Path(reference)
    original_directory = ROOT/'results/catalog-paired' if original_directory is None else Path(original_directory)
    original,_,original_branches,_,source = original_context(MODEL,original_directory,REVISION)
    failed_audit = audit_failed_branches(mpmath,reference)
    ref_report,mp_report = read(reference/'report.json'),read(mpmath/'report.json')
    cases = {k:{name:c[name] for name in ('ucs','cs','responses','branches')}
             for k,c in original['cases'].items() if c['status']!='passed'}
    required = {bid for c in cases.values() for bid in c['branches'].values()}
    excluded = {r['branch_id'] for r in ref_report['branches']}
    require(len(cases)==2 and len(required)==18 and len(excluded)==3 and excluded<=required,
            'Original failed-case coverage differs')
    selected = sorted(required-excluded)
    plan = {'model_id':MODEL,'model_sha256':MODEL_SHA256,'source_revision':REVISION,
            'original_report_sha256':digest(source),'original_archive_sha256':original['branch_archive']['sha256'],
            'reference_report_sha256':digest(reference/'report.json'),
            'original_case_count':original['expected_cases'],'original_passed_cases':original['passed_cases'],
            'cases':cases,'required_branch_ids':sorted(required),'excluded_original_failed_branch_ids':sorted(excluded),
            'selected_branch_ids':selected,'selected_branches':{bid:original_branches[bid] for bid in selected},
            'case_recovery_claimed':False}
    grid = sample_times(300.,.01,[ResetTrain(t,t+50.,{}) for t in (50.,150.,200.)],post_reset_offset=1e-5)
    report = validate_controls_metadata(controls,plan,ref_report,mp_report,grid)
    rows = {r['branch_id']:r for r in report['branches']}
    branches = {}
    for bid in sorted(required):
        provenance = {}
        if bid in excluded:
            traces = {}
            for name,directory in (('taylor',reference),('mpmath',mpmath)):
                path = directory/(bid+'.json'); record = read(path)
                provenance[name] = {'record_sha256':digest(path),'traces':record['traces']}
                for label,saved in record['traces'].items():
                    require(label not in traces, 'Duplicate branch integration')
                    traces[label] = trace(directory,saved,bid,label,grid)
        else:
            row = rows[bid]
            require(row['file']==bid+'.json', 'Unexpected control evidence path')
            path = controls/row['file']; record = read(path)
            require(record['fingerprint']==report['fingerprint'] and record['branch_id']==bid
                    and record['specification']==original_branches[bid]['specification']
                    and record['reset_trains']==original_branches[bid]['reset_trains'],
                    'Original control branch identity differs')
            require(record['case_recovery_claimed'] is False, 'Branch cannot claim case recovery')
            require(set(record['traces'])==set(record['integrations'])==set(REQUESTS),
                    'All five complete integrations are required')
            traces = {}
            for label,saved in record['traces'].items():
                validate_integration(label,record['integrations'][label],record['reset_trains'],report)
                traces[label] = trace(controls,saved,bid,label,grid)
            provenance['controls'] = {'record_sha256':digest(path),'traces':record['traces']}
        values = comparisons(traces)
        high,native = agreement(values)
        if bid not in excluded:
            require(record['comparisons']==values, 'Control comparisons do not reproduce')
            status = 'high_precision_agreement' if high else 'mismatch'
            require(record['high_precision_agreement']==high and record['native_agreement']==native
                    and record['status']==row['status']==status, 'Control outcome differs')
        branches[bid] = {'high_precision_agreement':high,'native_agreement':native,'comparisons':values,
                         'windows':{e:summarize(traces[e],WINDOWS) for e in ENGINES},'provenance':provenance}
    baseline_passed = (failed_audit['baseline_status']=='high_precision_agreement'
                       and failed_audit['baseline_native_agreement']
                       and read(reference/'untreated_baseline.json')['status']=='confirmed')
    results = score_cases(cases,branches,baseline_passed)
    recovered = sum(c['status']=='passed' for c in results.values())
    revalidation = original_cases_requiring_revalidation(original['cases'],branches)
    retained = original['passed_cases']-len(revalidation)
    combined = retained+recovered
    return {'purpose':__doc__,'model_id':MODEL,'model_sha256':MODEL_SHA256,
            'source_revision':REVISION,'original_report_sha256':digest(source),
            'original_archive_sha256':original['branch_archive']['sha256'],
            'control_report_sha256':digest(controls/'report.json'),
            'mpmath_report_sha256':digest(mpmath/'report.json'),'reference_report_sha256':digest(reference/'report.json'),
            'failed_branch_audit':failed_audit,'audit_script_sha256':digest(Path(__file__)),
            'scoring_source_sha256':{n:digest(ROOT/'grn_memory'/n)
                                      for n in ('paired_scores.py','catalog_paired.py','catalog_repeated.py')},
            'recovery_engines':list(ENGINES),'acceptance':ACCEPTANCE,'baseline_passed':baseline_passed,
            'required_branch_count':18,'high_precision_agreeing_branches':sum(b['high_precision_agreement'] for b in branches.values()),
            'native_agreeing_branches':sum(b['native_agreement'] for b in branches.values()),
            'original_case_count':original['expected_cases'],'original_passed_cases':original['passed_cases'],
            'retained_original_passed_cases':retained,'original_cases_requiring_revalidation':revalidation,
            'recovered_cases':recovered,'combined_passed_cases':combined,
            'all_cases_validated':combined==original['expected_cases'],
            'status':'passed' if combined==original['expected_cases'] else 'failed',
            'different_integrator_family_claimed':False,'branches':branches,'cases':results}


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controls',type=Path,required=True)
    parser.add_argument('--mpmath',type=Path,required=True)
    parser.add_argument('--reference',type=Path,default=ROOT/'results/catalog-paired-taylor-marhl')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    result = audit(args.controls,args.mpmath,args.reference)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    write_json(args.output,result)
    print(json.dumps({k:result[k] for k in ('model_id','status','required_branch_count',
          'high_precision_agreeing_branches','recovered_cases','combined_passed_cases')}))
