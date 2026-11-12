"""Independently recompute saved Radau/RoadRunner breaking comparisons.

This verifies full arrays and reset evidence without rerunning integration.
It produces window summaries for later case auditing, but neither recovers
cases nor validates an uncomputed conditional search.
"""

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import numpy as np
import pandas as pd

from grn_memory.breaking_audit import require
from grn_memory.catalog_breaking import trial_windows
from grn_memory.catalog_jax import source_hashes
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_repeated import summarize
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import comparison
from grn_memory.native_protocols import ResetTrain
from scripts.diagnose_scipy_breaking import prepare


META_KEYS=('model_id','model_sha256','source_evidence_sha256','source_report_sha256','source_fingerprint',
           'requests','acceptance','implementation_sha256','versions','sample_grid_sha256',
           'selected_branch_ids','case_recovery_claimed')
LABELS=('roadrunner','roadrunner_refined','scipy','scipy_refined')
SOURCES=('scripts/diagnose_scipy_breaking.py','grn_memory/scipy_reference.py','grn_memory/jax_protocols.py',
         'grn_memory/catalog_repeated.py','grn_memory/catalog_breaking.py',
         'grn_memory/native_protocols.py','grn_memory/catalog_validation.py')
PACKAGES={'jax','jaxlib','jaxkineticmodel','diffrax','equinox','scipy','numpy','pandas','libroadrunner','python-libsbml'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def trajectory(directory,bid,label,saved,times,names):
    require(saved['file']==bid+'-'+label+'.npz','Unexpected trajectory path')
    path=directory/saved['file']
    require(digest(path)==saved['sha256'],'Trajectory digest differs')
    with np.load(path,allow_pickle=False) as data:
        require(np.array_equal(data['times'],times) and list(data['observables'])==names,
                'Original observation inventory differs')
        require(data['values'].shape==(len(times),len(names)) and np.isfinite(data['values']).all(),
                'Complete finite trajectory array is required')
        result=pd.DataFrame(data['values'],columns=names);result.insert(0,'time',times)
    return result


def audit(directory):
    directory=Path(directory);report_path=directory/'report.json';report=read(report_path)
    require(report['status']=='completed','Diagnostic is still running')
    require(fingerprint({k:report[k] for k in META_KEYS})==report['fingerprint'],'Diagnostic fingerprint differs')
    require(report['case_recovery_claimed'] is False,'Branch diagnostic cannot claim case recovery')
    source=directory/'source-evidence.json'
    require(digest(source)==report['source_evidence_sha256'],'Captured source evidence differs')
    ids=report['selected_branch_ids']
    evidence,_,info,grid,originals=prepare(source,ids)
    require(ids==sorted(originals) and len(ids)==len(set(ids))==report['expected_branches']
            and len(report['branches'])==len(ids) and {r['record_id'] for r in report['branches']}==set(ids),
            'Selected branch inventory is incomplete')
    require(report['model_id']==evidence['original_report']['biomodel_id']
            and report['model_sha256']==info['sha256']
            and report['source_report_sha256']==evidence['original_report_sha256']
            and report['source_fingerprint']==evidence['original_report']['fingerprint'],
            'Original model or source identity differs')
    require(report['sample_grid_sha256']==hashlib.sha256(grid.tobytes()).hexdigest()
            and report['acceptance']=={'rtol':2e-5,'atol':1e-7},'Original grid or acceptance differs')
    sources=source_hashes();sources.update({n:digest(ROOT/n) for n in SOURCES})
    require(report['implementation_sha256']==sources,'Implementation source differs')
    require(set(report['versions'])==PACKAGES and all(isinstance(v,str) and v for v in report['versions'].values()),
            'Producer environment inventory is incomplete')
    requests=report['requests'];require(set(requests)==set(LABELS),'Integration request inventory differs')
    for engine,factor in (('roadrunner',2),('scipy',10)):
        expected_keys={'rtol','atol','method'} if engine=='scipy' else {'rtol','atol'}
        for label in (engine,engine+'_refined'):
            require(set(requests[label])==expected_keys,'Integration settings inventory differs')
            require(all(np.isfinite(requests[label][k]) and requests[label][k]>0 for k in ('rtol','atol')),
                    'Positive finite tolerances are required')
            if engine=='scipy':require(requests[label]['method']=='Radau','Radau method differs')
        require(all(requests[engine+'_refined'][k]==float(Decimal(str(requests[engine][k]))/factor)
                    and requests[engine+'_refined'][k]<requests[engine][k] for k in ('rtol','atol')),
                'Declared tolerance refinements differ')
    audited=[]
    for row in report['branches']:
        bid=row['record_id'];require(row['file']==bid+'.json','Unexpected branch path')
        path=directory/row['file'];require(digest(path)==row['sha256'],'Branch record digest differs')
        record=read(path);original=originals[bid];spec=original['specification'];times=grid[grid<=spec['stop']]
        require(record['record_id']==bid and record['fingerprint']==report['fingerprint']
                and record['specification']==spec and record['case_recovery_claimed'] is False,
                'Original branch identity or scope differs')
        require(all(requests['roadrunner'][k]<spec['integration_settings']['roadrunner'][k] for k in ('rtol','atol')),
                'RoadRunner settings do not refine the original request')
        require(set(record['integrations'])==set(LABELS),'All four integration outcomes are required')
        completed={k for k,v in record['integrations'].items() if v.get('completed') is True}
        require(set(record['traces'])==completed,'Trajectory inventory differs from completed integrations')
        trains=[ResetTrain(**t) for t in spec['reset_trains']]
        resets=sorted({float(v) for t in trains if t.values for v in t.times()})
        counts=[len(t.indices()) if t.values else 0 for t in trains]
        traces={}
        for label,outcome in record['integrations'].items():
            request=requests[label];require(outcome['request']==request,'Recorded integration request differs')
            if label not in completed:
                require(outcome['completed'] is False and isinstance(outcome.get('error'),str) and outcome['error'],
                        'An incomplete integration requires explicit failure evidence')
                continue
            require(outcome['sample_count']==len(times) and outcome['observables']==info['observables'],
                    'Integration observation coverage differs')
            if label.startswith('scipy'):
                require(outcome['backend']=='scipy.solve_ivp' and outcome['rhs_backend']=='Jaxkineticmodel'
                        and outcome['jacobian']=='jax.jacfwd' and outcome['method']=='Radau'
                        and outcome['model_sha256']==info['sha256'] and outcome['x64'] is True
                        and outcome['absolute_time_preserved'] is True
                        and all(outcome[k]==request[k] for k in ('rtol','atol')),'Radau implementation or clock differs')
                require(outcome['expected_resets']==outcome['performed_resets']==len(resets)
                        and outcome['expected_train_reset_counts']==outcome['train_reset_counts']==counts
                        and outcome['expected_segments']==outcome['completed_segments']==len(resets)+1
                        and outcome['last_interval']==[resets[-1] if resets else 0.,float(times[-1])],
                        'Reset or segment coverage is incomplete')
            traces[label]=trajectory(directory,bid,label,record['traces'][label],times,info['observables'])
        checks={a+'_vs_'+b:comparison(traces[a],traces[b],**report['acceptance'])
                for i,a in enumerate(LABELS) for b in LABELS[i+1:] if a in traces and b in traces}
        require(checks==record['comparisons'],'Saved pointwise comparisons do not reproduce')
        status=('incomplete' if len(checks)!=6 else 'confirmed' if all(c['passed'] for c in checks.values()) else 'mismatch')
        require(row['status']==record['status']==status,'Diagnostic outcome differs')
        audited.append({'record_id':bid,'status':status,'samples':len(times),'resets':len(resets),
                        'record_sha256':digest(path),'traces':record['traces'],'comparisons':checks,
                        'windows':{k:summarize(t,trial_windows(round((spec['stop']-1010.)/400.))) for k,t in traces.items()}})
    confirmed=sum(b['status']=='confirmed' for b in audited)
    require(report['confirmed_branches']==confirmed,'Confirmed branch count differs')
    return {'purpose':__doc__,'model_id':report['model_id'],'model_sha256':info['sha256'],
            'report_sha256':digest(report_path),'source_evidence_sha256':digest(source),
            'audit_script_sha256':digest(Path(__file__)),'selected_branch_count':len(ids),
            'complete_captured_failure_coverage':set(ids)=={b['record_id'] for b in evidence['failed_branches']},
            'confirmed_branches':confirmed,'all_selected_branches_confirmed':confirmed==len(ids),
            'case_recovery_claimed':False,'full_model_coverage_claimed':False,'branches':audited}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=audit(args.input)
    args.output.parent.mkdir(parents=True,exist_ok=True);write_json(args.output,result)
    print(json.dumps({k:result[k] for k in ('model_id','selected_branch_count','confirmed_branches',
                                          'complete_captured_failure_coverage')}))
