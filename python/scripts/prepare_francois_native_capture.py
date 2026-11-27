"""Capture all controls for the six unresolved original François trials.

Read the already published, checksummed full 118-case inventory. Keep its
outcomes intact and select every control of each unresolved third trial,
plus the full untreated baseline, before running any new integrations.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from grn_memory.catalog_runner import fingerprint
from grn_memory.breaking_audit import require

AUDIT_SHA = '162c7795ff4b6161e32b04ca47914a0493f00aa38fb6cc18f84592b9e995cda4'
STATUS_SHA = '1e6f58f66bddae312688861cc32bd6feb3fe0f901e146088f321482d1f9624eb'
BASE = 'cae38e9a6ec4c7567ea6cbf2908778f409a1ebb0'
MID = 'BIOMD0000000539'

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def records(archive, report, kind):
    result = {}
    for item in report['evidence_archives'][kind]:
        payload = archive.read(item['file'])
        require(len(payload) == item['bytes'] and hashlib.sha256(payload).hexdigest() == item['sha256'], 'Original record archive changed')
        rows = [json.loads(line) for line in gzip.decompress(payload).decode().splitlines()]
        require(len(rows) == item['records'], 'Original record count differs')
        for row in rows:
            require(row['record_id'] not in result, 'Duplicate record in a partition')
            result[row['record_id']] = row
    return result

def prepare(bundle):
    bundle = Path(bundle)
    require(digest(bundle/'expected-audit.json') == AUDIT_SHA and digest(bundle/'expected-status.json') == STATUS_SHA, 'Full published audit changed')
    manifest = json.loads((bundle/'manifest.json').read_text())
    for name, expected in manifest['files_sha256'].items():
        path = (bundle/name).resolve()
        require(path.is_relative_to(bundle.resolve()) and path.is_file() and not (bundle/name).is_symlink(), 'Unsafe original bundle member')
        require(digest(path) == expected, 'Published bundle member changed: '+name)
    audit = json.loads((bundle/'expected-audit.json').read_text())
    status = json.loads((bundle/'expected-status.json').read_text())
    require(audit['cases'] == 118 and audit['passed_cases'] == 80 and audit['complete_case_coverage'] is True, 'Full original scope differs')
    unknown = audit['unresolved_conditional_decisions']
    require(len(unknown) == 6 and len({x['case'] for x in unknown}) == 4, 'Original unresolved inventory differs')
    parts = {p['shard_index']: p for p in status['verified_artifacts']}
    require(set(parts) == set(range(16)), 'All sixteen original archives are required')
    for part in parts.values():
        path = bundle/'archives'/f'artifact-{part["artifact_id"]}.zip'
        require(path.stat().st_size == part['archive_bytes'] and 'sha256:'+digest(path) == part['archive_sha256'], 'Original ZIP changed')
    selected_shards = sorted({audit['case_summaries'][x['case']]['shard_index'] for x in unknown})
    branches, reports, case_records, trials, baseline = {}, {}, {}, [], None
    for index in selected_shards:
        part = parts[index]
        with zipfile.ZipFile(bundle/'archives'/f'artifact-{part["artifact_id"]}.zip') as archive:
            require(len(archive.namelist()) == len(set(archive.namelist())), 'Duplicate ZIP member')
            report_bytes = archive.read(MID+'.json')
            report = json.loads(report_bytes)
            require(report['network'] == 25 and report['biomodel_id'] == MID and report['engines'] == ['roadrunner','copasi'], 'Original model differs')
            reports[str(index)] = {'original_artifact':part, 'report_sha256':hashlib.sha256(report_bytes).hexdigest(), 'report':report}
            source_branches, cases = records(archive,report,'branches'), records(archive,report,'cases')
            keys = [x for x in unknown if audit['case_summaries'][x['case']]['shard_index'] == index]
            required = set()
            for item in keys:
                case = cases[audit['case_summaries'][item['case']]['record_id']]
                require(case['case_key'] == item['case'], 'Original case key differs')
                case_records[item['case']] = case
                trial = case['trials'][item['trial']]
                require(trial['trial'] == 3 and len(trial['branches']) == 8 and 'scores' not in trial, 'Expected unresolved third trial')
                trials.append({**item,'shard_index':index,'record':trial})
                required.update(trial['branches'].values())
            control = fingerprint({'reset_trains':[],'stop':2210.,'integration_settings':report['configuration']['integration_settings']})
            require(baseline in (None,control), 'Original baseline specification differs')
            baseline = control
            required.add(control)
            for bid in sorted(required):
                original = source_branches[bid]
                require(original['record_id'] == fingerprint(original['specification']) and original['fingerprint'] == report['fingerprint'], 'Original branch identity differs')
                row = branches.setdefault(bid, {'record_id':bid,'specification':original['specification'],
                    'sample_count':original['sample_count'],'occurrences':[]})
                require(row['specification'] == original['specification'] and row['sample_count'] == original['sample_count'], 'Shared branch specification differs')
                row['occurrences'].append({'shard_index':index,'artifact_id':part['artifact_id'],'record':original})
    require(len(branches) == 41 and len(trials) == 6 and baseline in branches, 'Complete diagnostic control inventory differs')
    errors = {bid for bid,row in branches.items() if any('windows' not in p['record'] for p in row['occurrences'])}
    require(len(errors) == 16, 'All sixteen incomplete native branches must be retained')
    for bid in errors:
        for occurrence in branches[bid]['occurrences']:
            original = occurrence['record']
            if 'windows' in original:
                continue
            require(original['error'].startswith('ValueError: Unexpected output shape ') and
                original['solver_attempts']['roadrunner'][-1]['status'] == 'completed' and
                original['solver_attempts']['copasi'][-1]['status'] == 'error', 'Original failure type differs')
    names = subprocess.check_output(['git','ls-tree','-r','--name-only',BASE,'python/grn_memory'],cwd=ROOT.parent,text=True).splitlines()
    source_files = {name.removeprefix('python/'):digest(ROOT/name.removeprefix('python/')) for name in names if name.endswith('.py')}
    source_files.update({name:digest(ROOT/name) for name in ('pyproject.toml','uv.lock','models/'+MID+'.xml','results/catalog-repeated/'+MID+'.json')})
    return {'schema':1,'network':25,'model_id':MID,'base_revision':BASE,
        'source_release':'kinetics-francois-inventory-20261125',
        'source_release_archive_sha256':'0271b999be45f6462fba044a653c8c273cae0c9c0e9b596ff2be5901e8b4110e',
        'original_full_audit_sha256':AUDIT_SHA,'original_full_status_sha256':STATUS_SHA,
        'original_full_audit':audit,'original_full_status':status,'source_reports':reports,'source_cases':case_records,
        'selection_rule':'Every control of every unresolved original third trial, plus the full untreated baseline; original settings unchanged',
        'selected_trials':sorted(trials,key=lambda x:(x['case'],x['trial'])),
        'baseline_branch_id':baseline,'branches':{k:branches[k] for k in sorted(branches)},
        'ordered_branch_ids':[baseline]+sorted(set(branches)-{baseline}),
        'original_incomplete_branch_ids':sorted(errors),'required_branches':41,'required_native_integrations':82,
        'full_original_cases':118,'full_original_partitions':16,'unchanged_repository_files_sha256':source_files,
        'acceptance':{'rtol':2e-5,'atol':1e-7},'local_numerical_integrations_performed':0,
        'case_recovery_claimed':False,'whole_model_pass_claimed':False,'goal_complete':False}

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();value=prepare(args.bundle)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:json.dump(value,stream,indent=2);stream.write('\n')
    print(json.dumps({'branches':value['required_branches'],'native_integrations':82,'unresolved_trials':6,'full_original_cases':118,'plan_sha256':digest(args.output),'numerical_integrations_performed':0}))
