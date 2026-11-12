"""Compute every remaining control arm for the two unresolved Marhl cases.

The three original failed branches have separate full precision diagnostics.
This selects their fifteen other required branches, preserving all twelve arms
per case. It saves full arrays for two independent Taylor implementations at two
precisions and for RoadRunner. Case recovery requires a separate combined audit.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from grn_memory.catalog_memory import write_json
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import comparison
from grn_memory.marhl_mpmath import MODEL_SHA256, NAMES
from grn_memory.native_protocols import ResetTrain, protocol_trajectory, sample_times
from scripts.audit_taylor_paired import audit as audit_reference
from scripts.recover_scipy_paired_cases import original_context


REQUESTS = {'taylor128': {'precision':128, 'tolerance':'1e-30'},
            'taylor192': {'precision':192, 'tolerance':'1e-45'},
            'mpmath128': {'precision':128, 'tolerance':'1e-30', 'degree':32},
            'mpmath192': {'precision':192, 'tolerance':'1e-45', 'degree':48},
            'roadrunner': {'rtol':1e-13, 'atol':1e-15}}
REVISION = '70a3afad61357e94873ff62a7300c099b4c7ae3e'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_versions():
    import heyoka
    # Conda's native build exposes __version__ without Python wheel metadata.
    return {'heyoka':heyoka.__version__,
            **{p:version(p) for p in ('mpmath','numpy','pandas','libroadrunner','python-libsbml')}}


def prepare_plan(original_directory=ROOT/'results/catalog-paired', reference=ROOT/'results/catalog-paired-taylor-marhl'):
    original, _, branches, info, source = original_context('BIOMD0000000039',original_directory,REVISION)
    if info['sha256'] != MODEL_SHA256 or info['observables'] != NAMES:
        raise ValueError('The original fixed Marhl model is required')
    audit_reference(reference)
    published = json.loads((reference/'report.json').read_text())
    cases = {k: {a:c[a] for a in ('ucs','cs','responses','branches')} for k,c in original['cases'].items()
             if c['status'] != 'passed'}
    required = {bid for c in cases.values() for bid in c['branches'].values()}
    excluded = {r['branch_id'] for r in published['branches']}
    if (len(cases) != 2 or len(required) != 18 or len(excluded) != 3 or not excluded <= required
            or excluded != {bid for bid,b in branches.items() if not b['passed']}):
        raise ValueError('The original complete case and failed-branch inventories are required')
    selected = sorted(required-excluded)
    return {'model_id':'BIOMD0000000039','model_sha256':MODEL_SHA256,'source_revision':REVISION,
            'original_report_sha256':digest(source),'original_archive_sha256':original['branch_archive']['sha256'],
            'reference_report_sha256':digest(reference/'report.json'),
            'original_case_count':original['expected_cases'],'original_passed_cases':original['passed_cases'],
            'cases':cases,'required_branch_ids':sorted(required),'excluded_original_failed_branch_ids':sorted(excluded),
            'selected_branch_ids':selected,'selected_branches':{bid:branches[bid] for bid in selected},
            'case_recovery_claimed':False}


def validate_outcome(label, evidence, times, trains):
    if not (evidence.get('completed') is True and evidence.get('request') == REQUESTS[label]
            and evidence.get('sample_count') == len(times) and evidence.get('observables') == NAMES):
        raise ValueError('Complete original observations and integration settings are required')
    if label == 'roadrunner':
        return
    counts = [len(ResetTrain(**t).indices()) if t['values'] else 0 for t in trains]
    resets = len({float(v) for t in trains if t['values'] for v in ResetTrain(**t).times()})
    request = REQUESTS[label]
    if not (evidence['model_sha256'] == MODEL_SHA256 and evidence['absolute_time_preserved'] is True
            and evidence['precision_bits'] == request['precision']
            and float(evidence['tolerance']) == float(request['tolerance'])
            and evidence['expected_resets'] == evidence['performed_resets'] == resets
            and evidence['expected_train_reset_counts'] == evidence['train_reset_counts'] == counts
            and evidence['expected_segments'] == evidence['completed_segments'] == resets+1):
        raise ValueError('Complete reset and precision evidence is required')
    if label.startswith('mpmath') and evidence['degree'] != request['degree']:
        raise ValueError('Taylor degree differs')


def load_trace(path, saved, times):
    if digest(path) != saved['sha256']:
        raise ValueError('Trajectory digest differs')
    with np.load(path,allow_pickle=False) as data:
        if (list(data['observables']) != NAMES or not np.array_equal(data['times'],times)
                or data['values'].shape != (len(times),len(NAMES)) or not np.isfinite(data['values']).all()):
            raise ValueError('Complete original trajectory array is required')
        result = pd.DataFrame(data['values'],columns=NAMES); result.insert(0,'time',times)
    return result


def diagnose(args):
    from grn_memory.marhl_mpmath import trajectory as mpmath_trajectory
    from grn_memory.taylor_reference import taylor_trajectory
    plan = prepare_plan()
    times = sample_times(300.,.01,[ResetTrain(t,t+50.,{}) for t in (50.,150.,200.)],post_reset_offset=1e-5)
    sources = ('scripts/diagnose_marhl_controls.py','scripts/recover_scipy_paired_cases.py',
               'grn_memory/marhl_mpmath.py','grn_memory/taylor_reference.py',
               'grn_memory/native_protocols.py','grn_memory/catalog_validation.py')
    metadata = {'plan_sha256':fingerprint(plan),'requests':REQUESTS,'acceptance':{'rtol':2e-5,'atol':1e-7},
                'sample_grid_sha256':hashlib.sha256(times.tobytes()).hexdigest(),'samples':len(times),
                'implementation_sha256':{name:digest(ROOT/name) for name in sources},
                'versions':runtime_versions(),
                'python':platform.python_version(),'case_recovery_claimed':False,
                'different_integrator_family_claimed':False}
    signature = fingerprint(metadata)
    report_path = args.output/'report.json'
    if report_path.exists():
        old = json.loads(report_path.read_text())
        if not args.resume or old['fingerprint'] != signature:
            raise ValueError('Existing results require --resume with unchanged sources and configuration')
    report = {'purpose':__doc__,**metadata,'fingerprint':signature,'status':'running',
              'expected_branches':15,'selected_branch_ids':plan['selected_branch_ids'],'branches':[],
              'started_at':datetime.now(timezone.utc).isoformat()}
    write_json(args.output/'plan.json',plan);write_json(report_path,report)
    for bid in plan['selected_branch_ids']:
        original = plan['selected_branches'][bid]; trains = original['reset_trains']
        destination = args.output/(bid+'.json')
        record = {'fingerprint':signature,'branch_id':bid,'specification':original['specification'],
                  'reset_trains':trains,'integrations':{},'traces':{},'comparisons':{},'status':'running',
                  'case_recovery_claimed':False}
        if args.resume and destination.exists():
            record = json.loads(destination.read_text())
            if (record['fingerprint'] != signature or record['branch_id'] != bid or record['reset_trains'] != trains
                    or record['specification'] != original['specification']):
                raise ValueError('Cached original branch identity differs')
        traces = {}
        for label,request in REQUESTS.items():
            array_path = args.output/(bid+'-'+label+'.npz')
            if record['integrations'].get(label,{}).get('completed') and label in record['traces']:
                validate_outcome(label,record['integrations'][label],times,trains)
                saved = record['traces'][label]
                if saved['file'] != array_path.name:raise ValueError('Unexpected cached trajectory path')
                traces[label] = load_trace(array_path,saved,times)
                continue
            evidence = {'request':request,'completed':False};record['integrations'][label]=evidence
            began = time.monotonic()
            def progress(row):
                if row['completed_segments'] % 100 == 0:
                    write_json(destination,record)
                    print(bid[:12],label,row['completed_segments'],row['last_interval'],flush=True)
            try:
                model_path = ROOT/'models/BIOMD0000000039.xml'
                if label == 'roadrunner':
                    trace = protocol_trajectory(model_path,times,[ResetTrain(**t) for t in trains],label,**request)
                    names,values = list(trace.columns[1:]),trace.iloc[:,1:].to_numpy()
                    evidence.update(completed=True,sample_count=len(times),observables=names)
                else:
                    function = mpmath_trajectory if label.startswith('mpmath') else taylor_trajectory
                    names,values = function(model_path,times,trains,**request,evidence=evidence,progress=progress)
                validate_outcome(label,evidence,times,trains)
                np.savez_compressed(array_path,times=times,values=values,observables=np.asarray(names))
                record['traces'][label] = {'file':array_path.name,'sha256':digest(array_path)}
                traces[label] = load_trace(array_path,record['traces'][label],times)
            except Exception as error:
                evidence.update(completed=False,error=f'{type(error).__name__}: {error}')
            evidence['seconds']=time.monotonic()-began;write_json(destination,record)
        labels = list(REQUESTS)
        pairs = [(a,b) for i,a in enumerate(labels) for b in labels[i+1:]]
        record['comparisons'] = {a+'_vs_'+b:comparison(traces[a],traces[b],**metadata['acceptance'])
                                 for a,b in pairs if a in traces and b in traces}
        high = [c for name,c in record['comparisons'].items() if not name.endswith('_vs_roadrunner')]
        native = [c for name,c in record['comparisons'].items() if name.endswith('_vs_roadrunner')]
        record['high_precision_agreement'] = len(high)==6 and all(c['passed'] for c in high)
        record['native_agreement'] = len(native)==4 and all(c['passed'] for c in native)
        record['status'] = ('incomplete' if len(record['comparisons'])!=10 else
                            'high_precision_agreement' if record['high_precision_agreement'] else 'mismatch')
        write_json(destination,record)
        report['branches'].append({'branch_id':bid,'file':destination.name,'status':record['status']})
        write_json(report_path,report)
        print(len(report['branches']),'/15',bid[:12],record['status'],flush=True)
    report.update(status='completed',finished_at=datetime.now(timezone.utc).isoformat())
    write_json(report_path,report)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    with (args.output/'.diagnostic.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        diagnose(args)
