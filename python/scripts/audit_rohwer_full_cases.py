"""Assemble verified Rohwer evidence and replay all 123 original failed cases.

All 11,674 branches are required. Original records, generated controls, incomplete
work and solver failures remain distinct. This program never integrates or
modifies producer evidence. It writes a new audit directory on each invocation.
"""

import argparse
from collections.abc import Mapping
from functools import lru_cache
from types import SimpleNamespace
import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.catalog_runner import fingerprint
from grn_memory.scipy_breaking_recovery import LABELS
from scripts import collect_rohwer_breaking_diagnostics as first
from scripts import collect_rohwer_later_controls as later
from scripts import run_rohwer_later_controls as producer
from scripts import audit_scipy_breaking_cases as case_math
from scripts.run_rohwer_later_controls import digest, read, require, write

FIRST_INPUTS = ROOT / 'results/catalog-breaking-rohwer-diagnostics-20261118'
LATER_PLAN = ROOT / 'results/catalog-breaking-rohwer-later-controls-20261118/plan.json'


def load_context(bundle):
    context = producer.load_plan(LATER_PLAN, later.PLAN_SHA, bundle)
    first_plan = first.producer.check(FIRST_INPUTS, first.PLAN_SHA)
    return context, first_plan


def scope(context, first_plan):
    plan, inventory, _, _, _ = context
    require(plan['requests'] == first.requests(SimpleNamespace(**first_plan['requests']))
            and plan['acceptance'] == first_plan['acceptance']
            and plan['model_id'] == first_plan['model_id'] and plan['model_sha256'] == first_plan['model_sha256']
            and sorted(inventory['cases']) == first_plan['original_failed_cases'],
            'Both diagnostic stages must share the original model, requests and complete failed-case scope')
    selected = {}
    for name, stage_plan in [('diagnostics', first_plan), ('controls', plan)]:
        for part in stage_plan['partitions']:
            for row in part['branches']:
                bid = row['record_id']
                require(bid not in selected, 'A branch appears in multiple evidence stages')
                batch = part.get('batch_index')
                if name == 'controls':
                    require(batch == part['index'] // 256 and type(batch) is int and 0 <= batch < 2,
                            'Control partition batch differs')
                selected[bid] = {'stage': name, 'partition': part['index'], 'batch_index': batch,
                                 'run_id': first.RUN['id'] if name == 'diagnostics' else later.RUNS[batch]['id']}
    require(len(selected) == 11674 and set(selected) == set(inventory['branches'])
            and len(inventory['cases']) == 123 and len(inventory['generated_potential_branch_ids']) == 848,
            'Complete 11674-branch, 123-case scope is required')
    counts = {name: sum(v['stage'] == name for v in selected.values())
              for name in ('diagnostics', 'controls')}
    require(counts == {'diagnostics': 750, 'controls': 10924},
            'Complete original stage allocation differs')
    require(selected[inventory['full_untreated_control']]['stage'] == 'controls'
            and all(selected[bid]['stage'] == 'controls' for bid in inventory['generated_potential_branch_ids']),
            'Every generated control and the baseline must be retained in the later stage')
    for bid, row in selected.items():
        row['origin'] = inventory['branch_origins'][bid]
    return {'model_id': inventory['model_id'], 'branches': selected, 'stage_counts': counts,
            'selected_case_keys': sorted(inventory['cases']), 'full_untreated_control': inventory['full_untreated_control'],
            'input_manifest_sha256': producer.MANIFEST_SHA, 'diagnostic_run': dict(first.RUN),
            'diagnostic_plan_sha256': first.PLAN_SHA, 'control_runs': [dict(run) for run in later.RUNS],
            'control_plan_sha256': later.PLAN_SHA, 'original_model_cases': 260,
            'original_passing_cases': 137, 'full_model_coverage_claimed': False}


class BranchStore(Mapping):
    """Keep full window evidence on disk and only a bounded case working set in RAM."""

    def __init__(self, directory, inventory):
        self.directory = directory
        self.index = {bid: {'status': 'pending', 'complete_diagnostic': False, 'verified_arrays': 0}
                      for bid in inventory['branches']}
        self._cached_read = lru_cache(maxsize=64)(self._read)

    def add(self, bid, row):
        require(bid in self.index and 'file' not in self.index[bid], 'Unknown or duplicate audited branch')
        require(row['record_id'] == bid and type(row['complete_diagnostic']) is bool,
                'Audited branch identity differs')
        path = self.directory / (bid + '.json')
        write(path, row)
        self.index[bid] = {'file': path.name, 'sha256': digest(path), 'status': row['status'],
                           'complete_diagnostic': row['complete_diagnostic'],
                           'verified_arrays': row['verified_arrays']}

    def _read(self, bid):
        entry = self.index[bid]
        require('file' in entry, 'Branch has no independently checked evidence')
        path = self.directory / entry['file']
        require(not path.is_symlink() and digest(path) == entry['sha256'], 'Stored branch audit changed')
        return read(path)

    def __getitem__(self, bid):
        return self._cached_read(bid)

    def __iter__(self):
        return iter(self.index)

    def __len__(self):
        return len(self.index)


def resolve_descriptor(value, parent):
    require(set(value) == {'selection', 'snapshots', 'cache'}, 'Stage evidence paths differ')
    return {name: (parent / path).resolve() for name, path in value.items()}


def stage_snapshots(name, paths, plan):
    require(name in ('diagnostics', 'controls'), 'Unknown evidence stage')
    keys = ('run', 'jobs', 'artifacts')
    snapshots = paths['snapshots']
    sources = {'selection': paths['selection']}
    batches = []
    for batch in ([None] if name == 'diagnostics' else [0, 1]):
        directory = snapshots if batch is None else snapshots / f'batch-{batch}'
        values = {key: read(directory / (key + '.json')) for key in keys}
        expected_jobs = 33 if batch is None else 257
        jobs, artifacts = values['jobs'], values['artifacts']
        require(jobs['total_count'] == len(jobs['jobs']) == expected_jobs
                and len({j['id'] for j in jobs['jobs']}) == expected_jobs
                and artifacts['total_count'] == len(artifacts['artifacts']),
                'Complete unique API inventories are required')
        batches.append(values)
        for key in keys:
            label = key if batch is None else f'batch-{batch}/{key}'
            sources[label] = directory / (key + '.json')
    selection = read(paths['selection'])
    bound = (first.bind_selection(plan, batches[0]['run'], batches[0]['jobs']) if name == 'diagnostics'
             else later.bind_selection(plan, [b['run'] for b in batches], [b['jobs'] for b in batches]))
    require(bound == selection, 'Fixed source selection differs')
    return selection, batches, sources


def preserve_snapshots(name, sources, output):
    hashes = {key: digest(path) for key, path in sources.items()}
    destination = output / 'api-snapshots' / name / fingerprint(hashes)
    for key, source in sources.items():
        target = destination / (key + '.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        require(not target.parent.is_symlink(), 'Unsafe snapshot destination')
        with target.open('xb') as stream:
            stream.write(source.read_bytes())
        require(digest(target) == hashes[key], 'Source snapshot changed during preservation')
    return {'directory': str(destination.resolve()), 'sha256': hashes}


def verify_stage(name, paths, context, first_plan, input_validation, output, store):
    """Recheck original ZIPs and complete branch reports; never trust status.json."""
    module = first if name == 'diagnostics' else later
    plan = first_plan if name == 'diagnostics' else context[0]
    selection, batches, sources = stage_snapshots(name, paths, plan)
    preserved = preserve_snapshots(name, sources, output)
    script = 'run_rohwer_breaking_diagnostics.py' if name == 'diagnostics' else 'run_rohwer_later_controls.py'
    source = first.RUN['head_sha'] if name == 'diagnostics' else later.SOURCE
    runner_sha = hashlib.sha256(subprocess.check_output(['git', 'show', source +
        ':python/scripts/' + script], cwd=ROOT)).hexdigest()
    pending, errors, partitions = [], [], []
    for row in selection['selected']:
        batch = row.get('batch_index')
        lineage = {'index': row['index'], 'batch_index': batch}
        try:
            snapshot = batches[0 if batch is None else batch]
            run, jobs, artifacts = (snapshot[key] for key in ('run', 'jobs', 'artifacts'))
            job = next(j for j in jobs['jobs'] if j['id'] == row['job_id'])
            module.validate_job(row, run, job)
            if job['status'] != 'completed':
                pending.append({**lineage, 'reason': 'job_' + job['status']})
                continue
            matches = [a for a in artifacts['artifacts'] if a['name'] == row['artifact_name']]
            if not matches:
                pending.append({**lineage, 'reason': 'no_artifact'})
                continue
            require(len(matches) == 1, 'Duplicate selected artifact')
            artifact = matches[0]
            module.validate_artifact(row, run, job, artifact)
            directory = paths['cache'] / str(run['id']) / 'attempt-1' / f'artifact-{artifact["id"]}'
            archive, evidence = directory / 'download.zip', directory / 'evidence'
            require(archive.is_file() and not archive.is_symlink() and evidence.is_dir()
                    and not evidence.is_symlink() and not directory.is_symlink(), 'Original cached ZIP or evidence is missing')
            require(digest(archive) == artifact['digest'].removeprefix('sha256:')
                    and archive.stat().st_size == artifact['size_in_bytes'], 'Original cached ZIP differs')
            files = first.verify_zip(archive, evidence)
            if name == 'diagnostics':
                checked = first.verify_partition(evidence, row, FIRST_INPUTS, plan, runner_sha)
            else:
                checked = later.verify_partition(evidence, row, context, runner_sha, input_validation)
            require([b['record_id'] for b in checked['branches']] == [b['record_id'] for b in row['branches']],
                    'Verified branch inventory differs from the exact selected partition')
            for branch in checked['branches']:
                bid = branch['record_id']
                require(bid in context[1]['branches'], 'Audited branch is outside full scope')
                windows = {}
                if branch['complete_diagnostic']:
                    independent = branch['independent_audit']
                    windows = (independent['branches'][0]['windows'] if name == 'diagnostics' else independent['windows'])
                store.add(bid, {**branch, 'windows': windows, 'origin': context[1]['branch_origins'][bid],
                               'stage': name, 'partition': row['index'], 'batch_index': batch,
                               'run_id': run['id'], 'run_attempt': run['run_attempt'], 'job_id': job['id'],
                               'job_conclusion': job['conclusion'], 'artifact_id': artifact['id'],
                               'evidence_directory': str((evidence / bid).resolve())})
            partitions.append({**lineage, 'run_id': run['id'], 'job_id': job['id'], 'job_conclusion': job['conclusion'],
                'artifact_id': artifact['id'], 'archive_sha256': artifact['digest'], 'evidence_sha256': files,
                'complete_selected_diagnostics': checked['complete_selected_diagnostics'],
                'producer_status': checked['producer_status'],
                'unverified_checkpoint_files': checked.get('unverified_checkpoint_files', [])})
        except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile) as error:
            errors.append({**lineage, 'error': f'{type(error).__name__}: {error}'})
    require(all(digest(path) == preserved['sha256'][key] for key, path in sources.items()),
            'Source API evidence changed during audit')
    return {'runs': [dict(b['run']) for b in batches], 'preserved_api_snapshots': preserved,
            'partitions': partitions, 'pending_partitions': pending, 'verification_errors': errors}


def replay(inventory, branches, captured, reference, config):
    require(set(branches) == set(inventory['branches']) and set(captured) == set(inventory['cases']),
            'All declared branches and original cases are required for replay')
    baseline = branches[inventory['full_untreated_control']]['status'] == 'confirmed'
    results = {}
    for key, value in inventory['cases'].items():
        result = case_math.evaluate_case(value['original_plan'], reference, config, branches, baseline)
        path = {name: {field: trial[field] for field in ('breakers', 'responses')}
                for name, trial in captured[key]['case']['trials'].items()}
        result['original_path'] = path
        for label in ('primary', 'refined'):
            new = {name: {field: trial[field] for field in ('breakers', 'responses')}
                   for name, trial in result[label + '_search']['trials'].items()}
            result[label + '_matches_original_path'] = new == path
        results[key] = result
    return baseline, results


def discrepancies(bundle, store):
    results = []
    for index in range(16):
        for bid, old in producer.inputs.read_records(bundle / f'original-branches-{index:02d}.jsonl.gz').items():
            if old['passed'] and store.index[bid]['status'] == 'confirmed':
                difference = case_math.summary_discrepancy(old, store[bid])
                if difference['max_scaled_error'] > 1:
                    results.append({'partition': index, 'record_id': bid, **difference})
    return results


def audit(bundle, sources_path, output):
    require(not output.exists(), 'Use a new full-case audit directory')
    context, first_plan = load_context(bundle)
    selected = scope(context, first_plan)
    validation = producer.inputs.validate(bundle, producer.MANIFEST_SHA)
    source_bytes = sources_path.read_bytes()
    sources = read(sources_path)
    require(set(sources) == {'diagnostics', 'controls'}, 'Every evidence stage must be declared')
    parent = sources_path.parent
    protected = [bundle.resolve()]
    protected_files = [sources_path.resolve()]
    for name in ('diagnostics', 'controls'):
        if sources[name] is not None:
            paths = resolve_descriptor(sources[name], parent)
            protected.extend(paths[k] for k in ('snapshots', 'cache'))
            protected_files.append(paths['selection'])
    require(not output.is_symlink() and not any(output.resolve().is_relative_to(path) for path in protected),
            'Audit output must be outside the input evidence directories')
    require(not any(path.is_relative_to(output.resolve()) for path in protected_files),
            'Audit output must be separate from source descriptor and selection files')
    output.mkdir(parents=True)
    (output / 'sources.json').write_bytes(source_bytes)
    write(output / 'scope.json', selected)
    write(output / 'input-validation.json', validation)
    branch_directory = output / 'branches'
    branch_directory.mkdir()
    store = BranchStore(branch_directory, context[1])
    stages, errors = {}, []
    for name in ('diagnostics', 'controls'):
        if sources[name] is None:
            stages[name] = {'status': 'not_supplied'}
            continue
        try:
            stages[name] = verify_stage(name, resolve_descriptor(sources[name], parent), context, first_plan,
                                       validation, output, store)
            errors.extend({'stage': name, **e} for e in stages[name]['verification_errors'])
        except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile) as error:
            errors.append({'stage': name, 'error': f'{type(error).__name__}: {error}'})
    missing = sorted(bid for bid, row in store.index.items() if not row['complete_diagnostic'])
    complete = not missing and not errors
    baseline, cases, contradictions = None, {}, []
    if complete:
        reference = read(ROOT / 'results/catalog-repeated' / (context[1]['model_id'] + '.json'))
        config = read(FIRST_INPUTS / 'source-partition-00.json')['original_report']['configuration']
        baseline, cases = replay(context[1], store, read(bundle / 'original-cases.json'), reference, config)
        contradictions = discrepancies(bundle, store)
    require(sources_path.read_bytes() == source_bytes, 'Evidence source descriptor changed during audit')
    result = {'schema_version': 1, 'model_id': context[1]['model_id'],
              'status': 'verification_failed' if errors else 'incomplete' if not complete else
                        'cases_confirmed' if all(c['passed'] for c in cases.values()) else 'complete_with_failures',
              'complete_selected_control_inventory': complete, 'required_branches': 11674, 'selected_cases': 123,
              'complete_branch_outcomes': sum(b['complete_diagnostic'] for b in store.index.values()),
              'verified_arrays': sum(b['verified_arrays'] for b in store.index.values()),
              'missing_or_incomplete_branches': missing, 'baseline_passed': baseline, 'cases': cases,
              'recovered_selected_cases': sum(c['passed'] for c in cases.values()),
              'original_passing_cases_included': False, 'full_model_coverage_claimed': False,
              'original_passing_branches_requiring_revalidation': contradictions,
              'cross_run_native_array_agreement_claimed': False, 'numerical_integrations_performed': 0,
              'stages': stages, 'verification_errors': errors,
              'source_descriptor_sha256': hashlib.sha256(source_bytes).hexdigest(),
              'scope_sha256': digest(output / 'scope.json'), 'input_validation': validation,
              'audit_script_sha256': digest(Path(__file__)), 'case_math_sha256': digest(Path(case_math.__file__)),
              'collector_sha256': {'diagnostics': digest(Path(first.__file__)), 'controls': digest(Path(later.__file__))}}
    write(output / 'branch-index.json', store.index)
    result['branch_index_sha256'] = digest(output / 'branch-index.json')
    write(output / 'audit.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['check', 'audit'])
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--sources', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.operation == 'check':
        require(not args.output.exists(), 'Use a new scope file')
        context, first_plan = load_context(args.inputs)
        result = scope(context, first_plan)
        result['input_validation'] = producer.inputs.validate(args.inputs, producer.MANIFEST_SHA)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write(args.output, result)
        print({'stage_counts': result['stage_counts'], 'selected_cases': len(result['selected_case_keys']),
               'numerical_integrations_performed': 0})
    else:
        require(args.sources is not None, 'Declare all evidence stages in a sources JSON file')
        result = audit(args.inputs, args.sources, args.output)
        print({k: result[k] for k in ('status', 'complete_branch_outcomes', 'verified_arrays', 'recovered_selected_cases')})
        sys.exit(1 if result['verification_errors'] else 0)
