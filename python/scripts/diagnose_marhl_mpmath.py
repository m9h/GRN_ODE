"""Cross-check the full Marhl precision diagnostic with mpmath.

mpmath integrates independently transcribed, checksummed model equations. Both
implementations use Taylor methods. These full-branch checks do not recover
complete cases or substitute for uncomputed control arms.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import mpmath
import numpy as np
import pandas as pd

from grn_memory.catalog_memory import write_json
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import comparison
from grn_memory.marhl_mpmath import MODEL_SHA256, NAMES, trajectory
from grn_memory.native_protocols import ResetTrain
from scripts.audit_taylor_paired import audit as audit_reference


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(path, expected_hash=None):
    if expected_hash is not None and digest(path) != expected_hash:
        raise ValueError("Trajectory SHA-256 differs")
    with np.load(path,allow_pickle=False) as arrays:
        names = list(arrays['observables']); times = arrays['times']; values = arrays['values']
        if names != NAMES or values.shape != (len(times),len(NAMES)) or not np.isfinite(values).all():
            raise ValueError("Complete finite model observations are required")
        result = pd.DataFrame(values,columns=names); result.insert(0,'time',times)
    return result


def validate_integration(evidence, request, times, trains):
    """Require full model, clock, sample and intervention coverage on resume."""
    counts = [len(ResetTrain(**t).indices()) if t['values'] else 0 for t in trains]
    resets = len({float(v) for t in trains if t['values'] for v in ResetTrain(**t).times()})
    if not (evidence.get('completed') is True
            and evidence.get('model_sha256') == MODEL_SHA256
            and evidence.get('backend') == 'mpmath.odefun'
            and evidence.get('mpmath_version') == mpmath.__version__
            and evidence.get('precision_bits') == request['precision']
            and float(evidence.get('tolerance', 'nan')) == float(request['tolerance'])
            and evidence.get('degree') == request['degree']
            and evidence.get('numeric_inputs') == 'binary64 values promoted exactly'
            and evidence.get('absolute_time_preserved') is True
            and evidence.get('expected_resets') == evidence.get('performed_resets') == resets
            and evidence.get('expected_train_reset_counts') == evidence.get('train_reset_counts') == counts
            and evidence.get('expected_segments') == evidence.get('completed_segments') == resets+1
            and evidence.get('sample_count') == len(times) and evidence.get('observables') == NAMES
            and evidence.get('last_interval', [None, None])[-1] == times[-1]
            and evidence.get('rhs_evaluations', 0) > 0):
        raise ValueError('Complete integration settings and coverage are required')


def diagnose(args):
    reference_audit = audit_reference(args.reference)
    source = json.loads((args.reference/'report.json').read_text())
    if source['model_sha256'] != MODEL_SHA256 or source['expected_branches'] != 3:
        raise ValueError("The complete original Marhl diagnostic is required")
    requests = {'mpmath128':{'precision':128,'tolerance':'1e-30','degree':32},
                'mpmath192':{'precision':192,'tolerance':'1e-45','degree':48}}
    metadata = {'model_id':'BIOMD0000000039','model_sha256':MODEL_SHA256,
        'reference_report_sha256':digest(args.reference/'report.json'),
        'reference_audit_sha256':fingerprint(reference_audit),'requests':requests,
        'acceptance':{'rtol':2e-5,'atol':1e-7},'mpmath_version':mpmath.__version__,
        'numpy_version':np.__version__,'pandas_version':pd.__version__,
        'python':platform.python_version(),
        'implementation_sha256':{name:digest(ROOT/name) for name in (
            'grn_memory/marhl_mpmath.py','grn_memory/catalog_validation.py','scripts/diagnose_marhl_mpmath.py')},
        'case_recovery_claimed':False,'different_integrator_family_claimed':False}
    signature = fingerprint(metadata)
    args.output.mkdir(parents=True,exist_ok=True)
    report_path = args.output/'report.json'
    if report_path.exists():
        previous = json.loads(report_path.read_text())
        if not args.resume or previous['fingerprint'] != signature:
            raise ValueError("Existing evidence requires --resume with unchanged configuration and sources")
    report = {'purpose':__doc__,**metadata,'fingerprint':signature,'status':'running',
              'expected_branches':3,'branches':[],'started_at':datetime.now(timezone.utc).isoformat()}
    write_json(report_path,report)
    write_json(args.output/'reference-audit.json',reference_audit)
    selections = [('untreated_baseline',source['baseline'])]
    selections.extend((row['branch_id'],row) for row in source['branches'])
    for bid,selection in selections:
        source_record = json.loads((args.reference/selection['file']).read_text())
        traces = {label:frame(args.reference/saved['file'],saved['sha256'])
                  for label,saved in source_record['traces'].items()}
        times = traces['taylor192']['time'].to_numpy()
        trains = source_record['reset_trains']
        destination = args.output/(bid+'.json')
        result = {'fingerprint':signature,'branch_id':bid,'reset_trains':trains,
            'reference_record_sha256':digest(args.reference/selection['file']),
            'reference_traces':source_record['traces'],'status':'running',
            'integrations':{},'traces':{},'comparisons':{}}
        if args.resume and destination.exists():
            result = json.loads(destination.read_text())
            if (result['fingerprint'] != signature or result['reset_trains'] != trains
                    or result['branch_id'] != bid
                    or result['reference_record_sha256'] != digest(args.reference/selection['file'])
                    or result['reference_traces'] != source_record['traces']):
                raise ValueError("Cached branch configuration differs")
        for label,request in requests.items():
            if result['integrations'].get(label,{}).get('completed') and label in result['traces']:
                validate_integration(result['integrations'][label],request,times,trains)
                saved = result['traces'][label]
                if saved['file'] != bid+'-'+label+'.npz':
                    raise ValueError("Unexpected cached trajectory path")
                traces[label] = frame(args.output/saved['file'],saved['sha256'])
                if not np.array_equal(traces[label]['time'],times):
                    raise ValueError("Cached observation grid differs")
                continue
            began = time.monotonic()
            evidence = {'completed':False}; result['integrations'][label] = evidence
            def progress(row):
                if row['completed_segments'] % 100 == 0:
                    write_json(destination,result)
                    print(bid[:12],label,row['completed_segments'],row['last_interval'],flush=True)
            try:
                names,values = trajectory(ROOT/'models/BIOMD0000000039.xml',times,trains,
                                          **request,evidence=evidence,progress=progress)
                validate_integration(evidence,request,times,trains)
                output = args.output/(bid+'-'+label+'.npz')
                np.savez_compressed(output,times=times,values=values,observables=np.asarray(names))
                result['traces'][label] = {'file':output.name,'sha256':digest(output)}
                traces[label] = frame(output,result['traces'][label]['sha256'])
            except Exception as error:
                evidence.update(completed=False,error=f'{type(error).__name__}: {error}')
            evidence['seconds'] = time.monotonic()-began
            write_json(destination,result)
        pairs = [('mpmath128','mpmath192')]
        pairs.extend((m,h) for m in requests for h in ('taylor128','taylor192','roadrunner'))
        result['comparisons'] = {a+'_vs_'+b:comparison(traces[a],traces[b],**metadata['acceptance'])
                                 for a,b in pairs if a in traces and b in traces}
        high = [c for name,c in result['comparisons'].items() if not name.endswith('_vs_roadrunner')]
        native = [c for name,c in result['comparisons'].items() if name.endswith('_vs_roadrunner')]
        result['high_precision_agreement'] = len(high)==5 and all(c['passed'] for c in high)
        result['native_agreement'] = len(native)==2 and all(c['passed'] for c in native)
        result['status'] = ('incomplete' if len(result['comparisons'])!=7 else
                            'high_precision_agreement' if result['high_precision_agreement'] else 'mismatch')
        result['case_recovery_claimed'] = False
        write_json(destination,result)
        if bid=='untreated_baseline':
            report['baseline'] = {'file':destination.name,'status':result['status']}
        else:
            report['branches'].append({'branch_id':bid,'file':destination.name,'status':result['status']})
        write_json(report_path,report)
        print(bid[:12],result['status'],'native agreement:',result['native_agreement'],flush=True)
    report.update(status='completed',finished_at=datetime.now(timezone.utc).isoformat())
    write_json(report_path,report)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,default=ROOT/'results/catalog-paired-taylor-marhl')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    with (args.output/'.diagnostic.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        diagnose(args)
