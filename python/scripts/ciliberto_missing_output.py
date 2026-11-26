"""Recover only authenticated missing outputs while retaining all Ciliberto controls.

The original numerical runner, arrays, comparisons and case mathematics are
unchanged. An isolated copy of the existing collector is bound to one exact new
run; its identity checks remain strict and the original collector is untouched.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import collect_ciliberto_later_controls as original
from scripts import run_ciliberto_later_controls as producer
from scripts.run_ciliberto_full_diagnostics import digest, read, require, write

INPUTS = ROOT/'results/catalog-breaking-ciliberto-missing-output-20261126'
CAPTURE_SHA = '38dbc0d7d4376f356fd281534b498b800576e384c81d30ab1572ebb20a78f771'
PLAN = ROOT/'results/catalog-breaking-ciliberto-later-controls-20261118/plan.json'
WORKFLOW = '.github/workflows/ciliberto-missing-output-recovery.yml'
SCRIPT = 'scripts/ciliberto_missing_output.py'
FROZEN_COLLECTOR_REVISION = 'b19f222cb6a83f4f4f07ec4b639adc0359b7cbfd'
GATE_NAME = 'validation'
DEPENDENCY_FILES = {'jaxkineticmodel/load_sbml/'+name for name in (
    'sbml_model.py', 'jax_kinetic_model.py', 'sympy_converter.py', 'export_sbml.py', 'sbml_load_utils.py')}


def check_runtime(plan):
    # The original runtime checker resolves installed dependency files from the
    # package location, not the repository. It also checks every package version.
    require(producer.runtime() == plan['runtime'], 'Frozen numerical source or installed runtime changed')
    files = plan['runtime']['source_hashes']
    require({name for name in files if name.startswith('jaxkineticmodel/')} == DEPENDENCY_FILES
            and {'pyproject.toml', 'uv.lock'} <= set(files), 'Frozen dependency inventory differs')
    return {name: sha for name, sha in files.items() if name not in DEPENDENCY_FILES}


def check_capture():
    require(digest(INPUTS/'recovery-plan.json') == CAPTURE_SHA, 'Pinned recovery capture differs')
    capture = read(INPUTS/'recovery-plan.json')
    expected = {'original-selection.json', 'original-api/run.json', 'original-api/jobs.json',
                'original-api/artifacts.json', 'missing-partition43-annotations.json'}
    require(set(capture['files']) == expected, 'Full original capture inventory differs')
    for name, sha in capture['files'].items():
        path = INPUTS/name
        require(not path.is_symlink() and digest(path) == sha, 'Original captured bytes differ: '+name)
    require(capture['repository'] == 'm9h/GRN_ODE' and capture['full_partitions'] == 256
            and capture['required_stage_branches'] == 6859 and capture['required_full_branches'] == 7334
            and capture['required_cases'] == 74 and capture['missing_indices'] == [43]
            and capture['missing_job_ids'] == [135288259512]
            and capture['case_recovery_claimed'] is False and capture['full_model_coverage_claimed'] is False,
            'Recovery cannot narrow the scientific scope')
    require(digest(PLAN) == capture['plan_sha256'] == original.PLAN_SHA, 'Original execution plan differs')
    plan, selection = read(PLAN), read(INPUTS/'original-selection.json')
    run, jobs, artifacts = (read(INPUTS/'original-api'/(n+'.json')) for n in ('run','jobs','artifacts'))
    require(original.bind_selection(plan, run, jobs) == selection, 'Full original job selection differs')
    require(artifacts['total_count'] == len(artifacts['artifacts']) == capture['captured_original_archives']
            and len({a['id'] for a in artifacts['artifacts']}) == artifacts['total_count'],
            'Complete unique original artifact pages required')
    require(sum(a['size_in_bytes'] for a in artifacts['artifacts']) == capture['captured_original_archive_bytes'],
            'Original archive inventory bytes differ')
    missing = []
    for row in selection['selected']:
        job = next(j for j in jobs['jobs'] if j['id'] == row['job_id'])
        matches = [a for a in artifacts['artifacts'] if a['name'] == row['artifact_name']]
        require(len(matches) <= 1, 'Duplicate original partition archive')
        if matches:
            original.validate_artifact(row, run, job, matches[0])
        elif job['status'] == 'completed':
            missing.append(row['index'])
    require(missing == capture['missing_indices'], 'Every terminal missing output must remain explicit')
    validate_missing(selection['selected'][43], run, jobs, artifacts)
    notes = read(INPUTS/'missing-partition43-annotations.json')
    require(any('lost communication' in note['message'] for group in notes for note in group),
            'Missing-output diagnosis must retain the original runner annotation')
    check_runtime(plan)
    return capture, plan, selection


def validate_missing(row, run, jobs, artifacts):
    require(jobs['total_count'] == len(jobs['jobs']) and artifacts['total_count'] == len(artifacts['artifacts']),
            'All original API pages required')
    require(row['index'] == 43 and row['job_id'] == 135288259512, 'Wrong missing original job')
    matches = [j for j in jobs['jobs'] if j['id'] == row['job_id']]
    require(len(matches) == 1, 'Missing original job identity')
    job = matches[0]
    original.validate_job(row, run, job)
    require(job['status'] == 'completed' and job['conclusion'] == 'failure', 'Do not replace a live original job')
    require(not any(a['name'] == row['artifact_name'] for a in artifacts['artifacts']),
            'An original artifact exists; audit it instead of selecting a replacement')


def indices(value):
    chosen = json.loads(value)
    require(chosen == [43] and type(chosen[0]) is int, 'Only the pinned missing partition 43 may be dispatched')
    return chosen


def source_proof(revision):
    require(isinstance(revision, str) and re.fullmatch('[0-9a-f]{40}', revision), 'Exact recovery revision required')
    _, plan, _ = check_capture()
    files = plan['runtime']['source_hashes']
    for name, sha in check_runtime(plan).items():
        payload = subprocess.check_output(['git','show',revision+':python/'+name], cwd=ROOT)
        require(hashlib.sha256(payload).hexdigest() == sha, 'Recovery revision changes frozen source: '+name)
    collector_file = 'scripts/collect_ciliberto_later_controls.py'
    frozen = subprocess.check_output(['git','show',FROZEN_COLLECTOR_REVISION+':python/'+collector_file], cwd=ROOT)
    require(hashlib.sha256(frozen).hexdigest() == digest(ROOT/collector_file), 'Original array collector changed')
    for name in (SCRIPT, collector_file):
        payload = subprocess.check_output(['git','show',revision+':python/'+name], cwd=ROOT)
        require(hashlib.sha256(payload).hexdigest() == digest(ROOT/name), 'Use the exact recovery collector source')
    workflow = subprocess.check_output(['git','show',revision+':'+WORKFLOW], cwd=ROOT)
    require(hashlib.sha256(workflow).hexdigest() == digest(ROOT.parent/WORKFLOW), 'Recovery workflow source differs')
    return {'revision':revision, 'frozen_numerical_files':dict(files),
            'original_collector_sha256':digest(ROOT/collector_file), 'recovery_collector_sha256':digest(ROOT/SCRIPT),
            'workflow_sha256':hashlib.sha256(workflow).hexdigest()}


def validate_run(run, revision):
    require(run['head_sha'] == revision and run['path'] == WORKFLOW and run['event'] == 'workflow_dispatch'
            and type(run['id']) is int and run['id'] > 0 and run['run_attempt'] == 1
            and type(run['workflow_id']) is int and run['workflow_id'] > 0,
            'Explicit recovery run, attempt or source differs')
    require(run['repository']['full_name'] == 'm9h/GRN_ODE', 'Recovery repository differs')


def bind(run, jobs, revision):
    _, plan, selection = check_capture()
    proof = source_proof(revision)
    validate_run(run, revision)
    require(jobs['total_count'] == len(jobs['jobs']) == 2 and len({j['id'] for j in jobs['jobs']}) == 2,
            'Exactly the validation gate and one recovery job are required')
    for j in jobs['jobs']:
        require(type(j['id']) is int and j['id'] > 0 and j['run_id'] == run['id']
                and j['run_attempt'] == 1 and j['head_sha'] == revision,
                'Recovery job source or attempt differs')
    gates = [j for j in jobs['jobs'] if j['name'] == GATE_NAME]
    require(len(gates) == 1 and gates[0]['status'] == 'completed' and gates[0]['conclusion'] == 'success',
            'Matching Linux validation must pass before binding the recovery')
    selected = deepcopy(selection['selected'])
    row = deepcopy(selected[43])
    matches = [j for j in jobs['jobs'] if j['name'] == row['job_name']]
    require(len(matches) == 1, 'Actual partition-43 recovery job is required')
    row.update(job_id=matches[0]['id'], previous=selected[43])
    selected[43] = row
    require(sum(a == b for a,b in zip(selected, selection['selected'], strict=True)) == 255,
            'Every other original selection must remain identical')
    return {'schema':1,'repository':'m9h/GRN_ODE','capture_sha256':CAPTURE_SHA,
            'original_selection_sha256':digest(INPUTS/'original-selection.json'),
            'recovery_run':{k:run[k] for k in ('id','run_attempt','workflow_id','head_sha','path')},
            'validation_job_id':gates[0]['id'],'source_proof':proof,'selected':selected,
            'full_partitions':256,'required_stage_branches':6859,'required_full_branches':7334,'required_cases':74,
            'case_recovery_claimed':False,'full_model_coverage_claimed':False}


def isolated_collector(run):
    """Bind checked provenance without mutating the original module or audit math."""
    spec = importlib.util.spec_from_file_location('_ciliberto_missing_output_bound', Path(original.__file__))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.RUN = {k:run[k] for k in ('id','run_attempt','workflow_id','head_sha','path')}
    return module


class Recovery:
    def __init__(self, descriptor):
        descriptor = Path(descriptor)
        value = read(descriptor)
        require(set(value) == {'binding','snapshots','cache'}, 'Recovery evidence paths differ')
        self.paths = {k:(descriptor.parent/v).resolve() for k,v in value.items()}
        self.binding = read(self.paths['binding'])
        self.run, self.jobs, self.artifacts = (read(self.paths['snapshots']/(n+'.json')) for n in ('run','jobs','artifacts'))
        require(self.binding == bind(self.run, self.jobs, self.binding['recovery_run']['head_sha']),
                'Full recovery binding differs from actual jobs')
        require(self.artifacts['total_count'] == len(self.artifacts['artifacts'])
                and len({a['id'] for a in self.artifacts['artifacts']}) == self.artifacts['total_count'],
                'Complete unique recovery artifact inventory required')
        self.module = isolated_collector(self.run)
        self.row = self.binding['selected'][43]
        self.job = next(j for j in self.jobs['jobs'] if j['id'] == self.row['job_id'])
        self.module.validate_job(self.row, self.run, self.job)
        self.runner_sha = self.binding['source_proof']['frozen_numerical_files']['scripts/run_ciliberto_later_controls.py']

    def validate_original(self, selection, run, jobs, artifacts):
        _, _, pinned = check_capture()
        require(selection == pinned, 'Original full selection changed before replacement')
        validate_missing(selection['selected'][43], run, jobs, artifacts)

    def preserve(self, output):
        directory = output/'recovery-provenance'
        directory.mkdir()
        sources = {'binding.json':self.paths['binding'],
                   **{n+'.json':self.paths['snapshots']/(n+'.json') for n in ('run','jobs','artifacts')}}
        for name, path in sources.items():
            require(not path.is_symlink(), 'Recovery provenance cannot be a symlink')
            (directory/name).write_bytes(path.read_bytes())
        return {'recovery_run':self.binding['recovery_run'],'validation_job_id':self.binding['validation_job_id'],
                'replaced_indices':[43],'unchanged_original_selections':255,
                'provenance_sha256':{name:digest(directory/name) for name in sources},
                'original_missing_job_id':135288259512,'full_partitions':256,
                'case_recovery_claimed':False,'full_model_coverage_claimed':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['check','matrix','bind'])
    parser.add_argument('--runtime', action='store_true')
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--indices', default='[43]')
    parser.add_argument('--run', type=Path)
    parser.add_argument('--jobs', type=Path)
    parser.add_argument('--revision')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    capture, plan, selection = check_capture()
    if args.runtime:
        producer.load_plan(PLAN, original.PLAN_SHA)
        require(args.inputs is not None, 'Authenticated complete inputs required')
        producer.inputs.validate(args.inputs, producer.MANIFEST_SHA)
        revision = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
        source_proof(revision)
    if args.operation == 'matrix':
        print(json.dumps({'index':indices(args.indices)},separators=(',',':')))
    elif args.operation == 'bind':
        require(args.run is not None and args.jobs is not None and args.revision is not None
                and args.output is not None and not args.output.exists(), 'Exact run, jobs, source and a new binding required')
        result = bind(read(args.run), read(args.jobs), args.revision)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write(args.output, result)
    else:
        print(json.dumps({'full_partitions':256,'later_controls':6859,'full_branches':7334,'cases':74,
                          'recovery_indices':capture['missing_indices'],'original_archives':capture['captured_original_archives'],
                          'numerical_integrations_performed':0}))


if __name__ == '__main__':
    main()
