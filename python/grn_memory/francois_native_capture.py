"""Run and audit the frozen native protocols behind six unresolved trials.

All forty trial controls and the untreated baseline are required. This records
native failures and original-path trial scores; it does not change the original
118-case inventory or claim complete-case or whole-model recovery.
"""
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
import time
from unittest.mock import patch

import basico
import COPASI
import numpy as np
import pandas as pd

from .breaking_audit import require
from .breaking_scores import classification_key, remaining_responses, trial_scores
from .catalog_breaking import branch_trains, candidate_plans, trial_windows
from .catalog_repeated import pulse_schedule, trains_for, summarize
from .catalog_runner import fingerprint
from .catalog_validation import PACKAGES, comparison, inspect_model
from .copasi_output_capture import digest, observe_time_course, copasi_messages
from .native_protocols import ResetTrain, encode_protocol, protocol_trajectory, sample_times

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT/'results/catalog-breaking-francois-native-capture-20261127/plan.json'
PLAN_SHA = '5e3eb51414365a40ee550e66cc2f034396589614cb708b1a9227eddd90a6a2c8'
MID = 'BIOMD0000000539'
ACCEPTANCE = {'rtol':2e-5,'atol':1e-7}
CAPTURE_FILES = ('grn_memory/francois_native_capture.py','grn_memory/copasi_output_capture.py',
                 'scripts/run_francois_native_capture.py','scripts/prepare_francois_native_capture.py')

def read(path):
    return json.loads(Path(path).read_text())

def write(path, value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')

def validate_scope(plan):
    require(plan['schema'] == 1 and plan['network'] == 25 and plan['model_id'] == MID and
            plan['full_original_cases'] == 118 and plan['full_original_partitions'] == 16, 'Full original model scope differs')
    old = plan['original_full_audit']
    require(old['cases'] == 118 and len(old['case_summaries']) == 118 and old['passed_cases'] == 80 and
            old['complete_case_coverage'] is True, 'Original audit was narrowed or reclassified')
    require(plan['acceptance'] == ACCEPTANCE and plan['case_recovery_claimed'] is False and
            plan['whole_model_pass_claimed'] is False, 'Acceptance or recovery claim differs')
    trials = plan['selected_trials']
    expected = sorted((t['case'],t['trial']) for t in old['unresolved_conditional_decisions'])
    require(len(trials) == 6 and [(t['case'],t['trial']) for t in trials] == expected, 'All six original unresolved trials are required')
    require(len(plan['branches']) == plan['required_branches'] == 41 and plan['required_native_integrations'] == 82,
            'Complete native control inventory differs')
    baseline = plan['baseline_branch_id']
    require(plan['ordered_branch_ids'] == [baseline]+sorted(set(plan['branches'])-{baseline}), 'Fixed branch order differs')
    used = {baseline}
    for trial in trials:
        require(trial['record'] == plan['source_cases'][trial['case']]['trials'][trial['trial']] and
                len(trial['record']['branches']) == 8, 'Original trial or control inventory differs')
        used.update(trial['record']['branches'].values())
    require(used == set(plan['branches']), 'Missing or extra original trial controls')
    failures = set()
    for bid,row in plan['branches'].items():
        require(row['record_id'] == bid == fingerprint(row['specification']) and row['sample_count'] == 221001,
                'Original branch specification or full horizon differs')
        require(row['occurrences'], 'Original provenance required')
        for occurrence in row['occurrences']:
            source = plan['source_reports'][str(occurrence['shard_index'])]
            original = occurrence['record']
            require(original['record_id'] == bid and original['specification'] == row['specification'] and
                    original['sample_count'] == row['sample_count'] and original['fingerprint'] == source['report']['fingerprint'] and
                    occurrence['artifact_id'] == source['original_artifact']['artifact_id'], 'Original branch provenance differs')
            if 'windows' not in original:
                failures.add(bid)
    require(sorted(failures) == plan['original_incomplete_branch_ids'] and len(failures) == 16,
            'Incomplete native branches were lost')
    return plan

def context():
    require(digest(PLAN) == PLAN_SHA, 'Pinned complete capture plan changed')
    plan = validate_scope(read(PLAN))
    for name, expected in plan['unchanged_repository_files_sha256'].items():
        require(digest(ROOT/name) == expected, 'Frozen numerical source or environment changed: '+name)
    path = ROOT/'models'/f'{MID}.xml'
    info = inspect_model(path)
    reference = read(ROOT/'results/catalog-repeated'/f'{MID}.json')
    cases = candidate_plans(reference)
    require(len(cases) == 118, 'Original calibrated case scope differs')
    for source in plan['source_reports'].values():
        report = source['report']
        require(report['model_sha256'] == info['sha256'] and report['reference_file_sha256'] == digest(ROOT/'results/catalog-repeated'/f'{MID}.json'), 'Frozen model or calibration differs')
        require(all(digest(ROOT/'grn_memory'/name) == sha for name,sha in report['implementation_sha256'].items()), 'Original numerical implementation differs')
        config = report['configuration']
        require(config['dt'] == .01 and config['post_reset_offset'] == 1e-5 and
                {k:config['comparison_'+k] for k in ('rtol','atol')} == ACCEPTANCE and not config['timed_drive_encoding'], 'Frozen grid or acceptance differs')
    for trial in plan['selected_trials']:
        case = cases[trial['case']]
        config = plan['source_reports'][str(trial['shard_index'])]['report']['configuration']
        settings = {**config['integration_settings'], **config['case_integration_overrides'].get(case['ucs'],{})}
        expected = {}
        for role,history,breaking in [('none',False,False),('history',True,False),('breaker',False,True),('history_breaker',True,True)]:
            for cue in (False,True):
                spec = {'reset_trains':[asdict(t) for t in branch_trains(case['ucs'],trial['record']['breakers'],history,breaking,cue,reference)],
                        'stop':2210.,'integration_settings':settings}
                expected[role+('_cue' if cue else '_sham')] = fingerprint(spec)
        require(trial['record']['branches'] == expected, 'Original trial controls or reset schedules differ')
    possible = trains_for(pulse_schedule(),{})+[ResetTrain(t,t+100.,{}) for t in (1010.,1210.,1410.,1610.,1810.,2010.)]
    grid = sample_times(2210.,.01,possible,post_reset_offset=1e-5)
    require(len(grid) == 221001, 'Complete sample grid differs')
    return plan,path,info,grid,reference

def runtime():
    return {'python':platform.python_version(),'system':platform.system(),'machine':platform.machine(),
            'packages':{p:version(p) for p in PACKAGES}}

def validate_runtime(value, plan):
    require(value['system'] == 'Linux' and value['machine'] == 'x86_64' and value['python'] == '3.12.13', 'Pinned Linux runtime required')
    require(all(value['packages'] == s['report']['versions'] for s in plan['source_reports'].values()), 'Original native package versions differ')

def source_hashes():
    return {name:digest(ROOT/name) for name in CAPTURE_FILES}

def select(plan,index):
    require(type(index) is int and 0 <= index < 41, 'Select one declared branch index')
    bid = plan['ordered_branch_ids'][index]
    return bid,plan['branches'][bid]

def protocol_bytes(path,trains):
    return encode_protocol(path,trains).encode('utf-8') if trains else path.read_bytes()

def run_branch(index, output):
    plan,path,info,times,_ = context()
    env = runtime();validate_runtime(env,plan)
    bid,original = select(plan,index)
    output = Path(output)
    require(not output.exists(), 'Use a fresh output; never overwrite an earlier native attempt')
    output.mkdir(parents=True)
    spec = original['specification']
    trains = [ResetTrain(**t) for t in spec['reset_trains']]
    (output/'protocol.xml').write_bytes(protocol_bytes(path,trains))
    record = {'schema':1,'plan_sha256':PLAN_SHA,'index':index,'record_id':bid,'specification':spec,
        'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'implementation_sha256':source_hashes(),'runtime':env,'model_sha256':info['sha256'],
        'protocol_sha256':digest(output/'protocol.xml'),'times_sha256':hashlib.sha256(times.tobytes()).hexdigest(),
        'samples':len(times),'observables':info['observables'],'acceptance':ACCEPTANCE,
        'started_at':datetime.now(timezone.utc).isoformat(),'status':'running','integrations':{},'trajectories':{},
        'comparison':None,'case_recovery_claimed':False,'whole_model_pass_claimed':False}
    write(output/'execution.json',record)
    traces = {}
    for engine in ('roadrunner','copasi'):
        request = spec['integration_settings'][engine]
        outcome = {'request':request,'completed':False,'status':'running'}
        record['integrations'][engine] = outcome
        write(output/'execution.json',record)
        began = time.monotonic()
        try:
            if engine == 'copasi':
                COPASI.CCopasiMessage.clearDeque()
                original_call = basico.run_time_course_with_output
                def observed(*args,**kwargs):
                    return observe_time_course(original_call,output/'copasi-raw.npz',outcome,*args,**kwargs)
                with patch.object(basico,'run_time_course_with_output',observed):
                    trace = protocol_trajectory(path,times,trains,engine,**request)
            else:
                trace = protocol_trajectory(path,times,trains,engine,**request)
            require(list(trace.columns) == ['time']+info['observables'] and len(trace) == len(times)
                    and np.isfinite(trace.to_numpy()).all(), 'Incomplete original observation inventory')
            np.testing.assert_allclose(trace.time.to_numpy(),times,rtol=0,atol=1e-9)
            destination = output/(engine+'.npz')
            np.savez_compressed(destination,times=trace.time.to_numpy(),values=trace.iloc[:,1:].to_numpy(),observables=np.asarray(info['observables']))
            record['trajectories'][engine] = {'file':destination.name,'sha256':digest(destination)}
            traces[engine] = trace
            outcome.update(completed=True,status='completed',samples=len(times))
        except Exception as error:
            outcome.update(status='integration_error',error=f'{type(error).__name__}: {error}')
            if engine == 'copasi':outcome.setdefault('copasi_messages',copasi_messages())
        outcome['seconds'] = time.monotonic()-began
        write(output/'execution.json',record)
        print(json.dumps({'index':index,'engine':engine,'status':outcome['status'],'error':outcome.get('error')}),flush=True)
    if len(traces) == 2:
        record['comparison'] = comparison(traces['roadrunner'],traces['copasi'],**ACCEPTANCE)
    record.update(status='completed',finished_at=datetime.now(timezone.utc).isoformat())
    write(output/'execution.json',record)
    return record

def safe_file(directory, saved, name):
    require(saved['file'] == name, 'Saved file name differs')
    path = directory/name
    require(path.is_file() and not path.is_symlink() and digest(path) == saved['sha256'], 'Saved output checksum differs')
    return path

def audit_result(directory, index, ctx=None, expected_revision=None):
    directory = Path(directory)
    plan,path,info,times,_ = ctx or context()
    bid,original = select(plan,index)
    record = read(directory/'execution.json')
    expected_revision = expected_revision or subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    require(record['source_revision'] == expected_revision, 'Selected producer revision differs')
    require(record['status'] == 'completed' and record['plan_sha256'] == PLAN_SHA and record['index'] == index
            and record['record_id'] == bid and record['specification'] == original['specification'], 'Complete selected execution required')
    require(record['implementation_sha256'] == source_hashes() and record['model_sha256'] == info['sha256'] and
            record['samples'] == len(times) and record['observables'] == info['observables'] and
            record['times_sha256'] == hashlib.sha256(times.tobytes()).hexdigest() and record['acceptance'] == ACCEPTANCE,
            'Frozen source, model, samples or acceptance differs')
    validate_runtime(record['runtime'],plan)
    require(record['case_recovery_claimed'] is False and record['whole_model_pass_claimed'] is False, 'Producer cannot claim case recovery')
    trains = [ResetTrain(**t) for t in original['specification']['reset_trains']]
    protocol = directory/'protocol.xml'
    require(not protocol.is_symlink() and digest(protocol) == record['protocol_sha256'] and protocol.read_bytes() == protocol_bytes(path,trains), 'Encoded original protocol differs')
    encoded = inspect_model(protocol)
    require(set(record['integrations']) == {'roadrunner','copasi'}, 'Both original native integrations required')
    complete = {e for e,o in record['integrations'].items() if o['completed'] is True}
    require(set(record['trajectories']) == complete, 'Saved array inventory differs')
    traces,windows = {},{}
    for engine,outcome in record['integrations'].items():
        require(outcome['request'] == original['specification']['integration_settings'][engine] and
                type(outcome['completed']) is bool, 'Original numerical request differs')
        if not outcome['completed']:
            require(outcome['status'] == 'integration_error' and isinstance(outcome.get('error'),str) and outcome['error'], 'Failure needs explicit evidence')
            continue
        require(outcome['samples'] == len(times) and outcome['status'] == 'completed', 'Incomplete integration')
        array = safe_file(directory,record['trajectories'][engine],engine+'.npz')
        with np.load(array,allow_pickle=False) as z:
            require(set(z.files) == {'times','values','observables'} and z['times'].shape == times.shape and
                    list(z['observables']) == info['observables'] and z['values'].shape == (len(times),len(info['observables'])),
                    'Incomplete saved observation inventory')
            require(z['values'].dtype == np.float64 and np.isfinite(z['values']).all(), 'Invalid full trajectory')
            np.testing.assert_allclose(z['times'],times,rtol=0,atol=1e-9)
            trace = pd.DataFrame(z['values'].copy(),columns=info['observables']);trace.insert(0,'time',z['times'].copy())
        traces[engine] = trace
        windows[engine] = summarize(trace,trial_windows(3))
    expected = comparison(traces['roadrunner'],traces['copasi'],**ACCEPTANCE) if len(traces) == 2 else None
    require(record['comparison'] == expected, 'Saved native comparison does not reproduce')
    capture = record['integrations']['copasi']
    native = {'completed':capture['completed'],'error':capture.get('error'),'raw_output_available':'raw_output' in capture}
    if 'raw_output' in capture:
        request = original['specification']['integration_settings']['copasi']
        require(capture['settings'] == {'r_tol':request['rtol'],'a_tol':request['atol'],'max_steps':100000,
                'automatic':False,'output_event':False,'method':'deterministic'}, 'COPASI effective request differs')
        require(capture['requested_samples'] == len(times) and capture['requested_times_sha256'] == record['times_sha256'], 'COPASI received a different sample grid')
        raw = safe_file(directory,capture['raw_output'],'copasi-raw.npz')
        with np.load(raw,allow_pickle=False) as z:
            require(set(z.files) == {'values','columns'} and list(z['values'].shape) == capture['shape'] and
                    list(z['columns']) == capture['columns'], 'Raw COPASI output inventory differs')
            values = z['values'].copy()
        require(values.ndim == 2 and values.shape[1] == len(encoded['observables'])+1, 'Raw encoded observable count differs')
        native.update(returned_rows=len(values),required_rows=len(times),last_time=float(values[-1,0]) if len(values) else None)
        if capture['completed']:
            np.testing.assert_allclose(values[:,0],times,rtol=0,atol=1e-9)
            require(np.array_equal(values[:,0],traces['copasi'].time.to_numpy()), 'Accepted clock differs from raw COPASI output')
            columns = [encoded['observables'].index(name)+1 for name in info['observables']]
            require(np.array_equal(values[:,columns],traces['copasi'].iloc[:,1:].to_numpy()), 'Accepted trajectory differs from raw COPASI output')
            for i,train in enumerate(trains):
                if train.values and len(train.indices()):
                    require(values[-1,encoded['observables'].index(f'grn_protocol_{i}_count')+1] == train.indices().stop, 'Incomplete raw reset counter')
    else:
        require(not capture['completed'], 'Completed COPASI trajectory lacks its raw capture')
    if 'timecourse_log' in capture:
        log = safe_file(directory,capture['timecourse_log'],'copasi-raw.log.gz')
        text = gzip.decompress(log.read_bytes()).decode('utf-8')
        require(len(text.encode('utf-8')) == capture['timecourse_log']['uncompressed_bytes'] and
                text[-1500:] == capture['timecourse_log']['tail'], 'Saved solver log does not reproduce')
        native.update(step_limit_exhausted='MXSTEP' in text and "I1 = '100000'" in text,
                      clock_resolution_warning='T + H = T' in text,log_sha256=digest(log))
    return {'index':index,'record_id':bid,'execution_sha256':digest(directory/'execution.json'),
        'verified_complete_arrays':len(traces),'comparison':expected,'native_copasi':native,
        'partial_windows':windows,'windows':windows if len(traces)==2 else None,
        'status':'confirmed' if expected and expected['passed'] else 'mismatch' if expected else 'native_integration_failure',
        'case_recovery_claimed':False,'whole_model_pass_claimed':False}

def replay_trials(audited, ctx=None):
    plan,_,_,_,reference = ctx or context()
    require(len(audited) == 41 and {r['record_id'] for r in audited} == set(plan['branches']), 'All forty controls and baseline must be audited')
    branches = {r['record_id']:r for r in audited}
    cases = candidate_plans(reference)
    outcomes = []
    for selected in plan['selected_trials']:
        trial = selected['record'];cells = {role:branches[bid] for role,bid in trial['branches'].items()}
        row = {'case':selected['case'],'trial':selected['trial'],'responses':trial['responses'],
               'branches':trial['branches'],'original_trial_was_unresolved':True}
        if any(b['windows'] is None for b in cells.values()):
            row.update(status='unresolved_native_failure',incomplete_controls=[r for r,b in cells.items() if b['windows'] is None])
        else:
            scores = {e:trial_scores(cells,e,trial['responses'],cases[selected['case']]['responses'],3) for e in ('roadrunner','copasi')}
            disagreements = [r for r in trial['responses'] if classification_key(scores['roadrunner'][r]) != classification_key(scores['copasi'][r])]
            row.update(scores=scores,controlled_classification_disagreements=disagreements,
                remaining_responses=remaining_responses(scores,trial['responses'],['roadrunner','copasi']),
                status='agreement' if not disagreements and all(b['status']=='confirmed' for b in cells.values()) else 'numerical_disagreement')
        outcomes.append(row)
    return {'full_original_cases':118,'original_passing_cases_unchanged':80,'original_failed_cases_unchanged':38,
        'required_branches':41,'verified_complete_arrays':sum(r['verified_complete_arrays'] for r in audited),
        'baseline_status':branches[plan['baseline_branch_id']]['status'],'selected_original_path_trials':outcomes,
        'unresolved_native_trials':sum(t['status']=='unresolved_native_failure' for t in outcomes),
        'case_recovery_claimed':False,'whole_model_pass_claimed':False,'goal_complete':False}
