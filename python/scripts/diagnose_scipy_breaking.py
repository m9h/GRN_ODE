"""Check complete breaking branches with Radau and a declared native reference.

Preserve each captured branch's entire grid and reset schedule, saving all raw
arrays. These branch diagnostics do not recover complete cases or recompute
the conditional search. No native failure is overwritten.
"""

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import numpy as np
import pandas as pd

from grn_memory.catalog_jax import source_hashes
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_repeated import pulse_schedule,trains_for
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import comparison
from grn_memory.jax_protocols import supported_model
from grn_memory.native_protocols import ResetTrain,encode_protocol,sample_times,protocol_trajectory
from grn_memory.scipy_reference import scipy_protocol_trajectory


ACCEPTANCE={'rtol':2e-5,'atol':1e-7}
PACKAGES={'jax','jaxlib','jaxkineticmodel','diffrax','equinox','scipy',
          'numpy','pandas','libroadrunner','python-libsbml'}


def native_engine(args):
    engine=getattr(args,'reference_engine','roadrunner')
    if engine not in ('roadrunner','copasi'):
        raise ValueError('Choose RoadRunner or COPASI as the native reference')
    return engine


def native_packages(engine):
    if engine not in ('roadrunner','copasi'):
        raise ValueError('Unknown native reference engine')
    return PACKAGES | ({'python-copasi','copasi-basico'} if engine=='copasi' else set())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def requests(args):
    engine=native_engine(args)
    divided=lambda value,factor:float(Decimal(str(value))/factor)
    result={engine:{'rtol':args.reference_rtol,'atol':args.reference_atol},
            engine+'_refined':{'rtol':divided(args.reference_rtol,2),'atol':divided(args.reference_atol,2)},
            'scipy':{'method':'Radau','rtol':args.rtol,'atol':args.atol},
            'scipy_refined':{'method':'Radau','rtol':divided(args.rtol,10),'atol':divided(args.atol,10)}}
    if any(not np.isfinite(row[k]) or row[k]<=0 for row in result.values() for k in ('rtol','atol')):
        raise ValueError('Positive finite integration tolerances are required')
    return result


def prepare(evidence_path,selected=()):
    evidence=json.loads(evidence_path.read_text());original=evidence['original_report']
    path=ROOT/'models'/(original['biomodel_id']+'.xml');info=supported_model(path)
    config=original['configuration']
    if (info['sha256']!=original['model_sha256'] or original['engines']!=['roadrunner','copasi']
            or config['dt']!=.01 or config['post_reset_offset']!=1e-5
            or {k:config['comparison_'+k] for k in ('rtol','atol')}!=ACCEPTANCE
            or config.get('timed_drive_encoding')):
        raise ValueError('Matching original autonomous ODE model, grid and acceptance are required')
    possible=trains_for(pulse_schedule(),{})+[ResetTrain(t,t+100.,{}) for t in (1010.,1210.,1410.,1610.,1810.,2010.)]
    grid=sample_times(2210.,.01,possible,post_reset_offset=1e-5)
    branches={b['record_id']:b for b in evidence['failed_branches']}
    if not branches or len(branches)!=len(evidence['failed_branches']) or set(selected)-branches.keys():
        raise ValueError('Unique known original failed branches are required')
    for bid,b in branches.items():
        spec=b['specification'];times=grid[grid<=spec['stop']]
        if (b['passed'] or b['fingerprint']!=original['fingerprint'] or fingerprint(spec)!=bid
                or spec['stop'] not in (1010.,1410.,1810.,2210.) or len(times)!=b['sample_count']):
            raise ValueError('Original branch identity or observation inventory differs')
        encode_protocol(path,[ResetTrain(**t) for t in spec['reset_trains']])
    ids=sorted(set(selected)) if selected else sorted(branches)
    return evidence,path,info,grid,{bid:branches[bid] for bid in ids}


def load_saved(path,saved,times,names,evidence,label,request,trains,model_sha):
    if digest(path)!=saved['sha256'] or saved['file']!=path.name:
        raise ValueError('Saved trajectory identity differs')
    if not (evidence['completed'] is True and evidence['request']==request
            and evidence['sample_count']==len(times) and evidence['observables']==names):
        raise ValueError('Complete integration observations and settings are required')
    if label.startswith('scipy'):
        resets=sorted({float(v) for t in trains if t.values for v in t.times()})
        counts=[len(t.indices()) if t.values else 0 for t in trains]
        if not (evidence['model_sha256']==model_sha and evidence['method']==request['method']
                and evidence['rtol']==request['rtol'] and evidence['atol']==request['atol']
                and evidence['x64'] is True and evidence['absolute_time_preserved'] is True
                and evidence['expected_resets']==evidence['performed_resets']==len(resets)
                and evidence['expected_train_reset_counts']==evidence['train_reset_counts']==counts
                and evidence['expected_segments']==evidence['completed_segments']==len(resets)+1
                and evidence['last_interval']==[resets[-1] if resets else 0.,float(times[-1])]):
            raise ValueError('Complete Radau reset, precision and clock evidence is required')
    with np.load(path,allow_pickle=False) as data:
        if not (set(data.files)=={'times','values','observables'}
                and data['times'].dtype==np.float64 and data['values'].dtype==np.float64
                and np.array_equal(data['times'],times) and list(data['observables'])==names
                and data['values'].shape==(len(times),len(names)) and np.isfinite(data['values']).all()):
            raise ValueError('Complete original trajectory array is required')
        trace=pd.DataFrame(data['values'],columns=names);trace.insert(0,'time',times)
    return trace


def diagnose(args):
    evidence,path,info,grid,branches=prepare(args.evidence,args.branch)
    settings=requests(args);engine=native_engine(args)
    for original in branches.values():
        native=original['specification']['integration_settings'][engine]
        if any(settings[engine][k]>=native[k] for k in ('rtol','atol')):
            raise ValueError('Both native tolerances must refine the original request')
    sources=source_hashes()
    sources.update({name:digest(ROOT/name) for name in ('scripts/diagnose_scipy_breaking.py',
                    'grn_memory/scipy_reference.py','grn_memory/jax_protocols.py','grn_memory/catalog_repeated.py',
                    'grn_memory/catalog_breaking.py','grn_memory/native_protocols.py','grn_memory/catalog_validation.py')})
    metadata={'model_id':evidence['original_report']['biomodel_id'],'model_sha256':info['sha256'],
              'source_evidence_sha256':digest(args.evidence),'source_report_sha256':evidence['original_report_sha256'],
              'source_fingerprint':evidence['original_report']['fingerprint'],
              'reference_engine':engine,'requests':settings,'acceptance':ACCEPTANCE,'implementation_sha256':sources,
              'versions':{p:version(p) for p in sorted(native_packages(engine))},
              'sample_grid_sha256':hashlib.sha256(grid.tobytes()).hexdigest(),
              'selected_branch_ids':sorted(branches),'case_recovery_claimed':False}
    signature=fingerprint(metadata);destination=args.output/'report.json'
    if destination.exists() and (not args.resume or json.loads(destination.read_text())['fingerprint']!=signature):
        raise ValueError('Resume requires unchanged source, configuration and environment')
    report={'purpose':__doc__,**metadata,'fingerprint':signature,'expected_branches':len(branches),
            'status':'running','branches':[],'started_at':datetime.now(timezone.utc).isoformat()}
    write_json(args.output/'source-evidence.json',evidence);write_json(destination,report)
    for bid,original in branches.items():
        spec=original['specification'];times=grid[grid<=spec['stop']]
        trains=[ResetTrain(**t) for t in spec['reset_trains']];record_path=args.output/(bid+'.json')
        record={'fingerprint':signature,'record_id':bid,'specification':spec,'integrations':{},'traces':{},
                'comparisons':{},'status':'running','case_recovery_claimed':False}
        if args.resume and record_path.exists():
            record=json.loads(record_path.read_text())
            if record['fingerprint']!=signature or record['record_id']!=bid or record['specification']!=spec:
                raise ValueError('Cached original branch identity differs')
        traces={}
        for label,request in settings.items():
            array_path=args.output/(bid+'-'+label+'.npz')
            if record['integrations'].get(label,{}).get('completed') and label in record['traces']:
                traces[label]=load_saved(array_path,record['traces'][label],times,info['observables'],
                                         record['integrations'][label],label,request,trains,info['sha256'])
                continue
            outcome={'request':request,'completed':False};record['integrations'][label]=outcome
            began=time.monotonic()
            def progress(row):
                if row['completed_segments']%500==0:
                    write_json(record_path,record)
                    print(bid[:12],label,row['completed_segments'],row['last_interval'],flush=True)
            try:
                if label.startswith('scipy'):
                    trajectory=scipy_protocol_trajectory(path,times,trains,**request,evidence=outcome,progress=progress)
                    outcome['observables']=list(trajectory.columns[1:])
                else:
                    trajectory=protocol_trajectory(path,times,trains,engine,**request)
                    outcome.update(completed=True,sample_count=len(times),observables=list(trajectory.columns[1:]))
                if not np.array_equal(trajectory.time.to_numpy(),times):raise ValueError('Observation times differ')
                np.savez_compressed(array_path,times=times,values=trajectory.iloc[:,1:].to_numpy(),
                                    observables=np.asarray(list(trajectory.columns[1:])))
                record['traces'][label]={'file':array_path.name,'sha256':digest(array_path)}
                traces[label]=load_saved(array_path,record['traces'][label],times,info['observables'],
                                         outcome,label,request,trains,info['sha256'])
            except Exception as error:
                outcome.update(completed=False,error=f'{type(error).__name__}: {error}')
            outcome['seconds']=time.monotonic()-began;write_json(record_path,record)
        labels=list(settings)
        record['comparisons']={a+'_vs_'+b:comparison(traces[a],traces[b],**ACCEPTANCE)
                               for i,a in enumerate(labels) for b in labels[i+1:] if a in traces and b in traces}
        record['status']=('incomplete' if len(record['comparisons'])!=6 else
                           'confirmed' if all(c['passed'] for c in record['comparisons'].values()) else 'mismatch')
        write_json(record_path,record)
        report['branches'].append({'record_id':bid,'file':record_path.name,'sha256':digest(record_path),'status':record['status']})
        write_json(destination,report)
        print(len(report['branches']),'/',len(branches),bid[:12],record['status'],flush=True)
    report.update(status='completed',confirmed_branches=sum(b['status']=='confirmed' for b in report['branches']),
                  finished_at=datetime.now(timezone.utc).isoformat())
    write_json(destination,report)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--branch',action='append',default=[])
    parser.add_argument('--rtol',type=float,default=1e-10)
    parser.add_argument('--atol',type=float,default=1e-12)
    parser.add_argument('--reference-rtol',type=float,default=1e-13)
    parser.add_argument('--reference-atol',type=float,default=1e-15)
    parser.add_argument('--reference-engine',choices=('roadrunner','copasi'),default='roadrunner',
                        help='Explicit native reference; never switched automatically after a mismatch')
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    with (args.output/'.diagnostic.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        diagnose(args)
