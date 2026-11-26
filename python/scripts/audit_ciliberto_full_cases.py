"""Assemble verified Ciliberto evidence and replay all 74 original failed cases.

All 7,334 branches are required. Original records, generated controls, incomplete
work and solver failures remain distinct. This program never integrates or
modifies producer evidence. It writes a new audit directory on each invocation.
"""

import argparse
from collections.abc import Mapping
from contextlib import nullcontext
from functools import lru_cache
import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.catalog_breaking import trial_windows
from grn_memory.catalog_repeated import summarize
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import comparison
from grn_memory.native_protocols import ResetTrain
from grn_memory.scipy_breaking_recovery import LABELS
from scripts import collect_ciliberto_full_diagnostics as first
from scripts import collect_ciliberto_later_controls as later
from scripts import run_ciliberto_later_controls as producer
from scripts import audit_scipy_breaking_cases as case_math
from scripts.audit_scipy_breaking import trajectory
from scripts.run_ciliberto_full_diagnostics import digest, read, require, write

FIRST_INPUTS = ROOT / 'results/catalog-breaking-ciliberto-full-diagnostics-20261118'
LATER_PLAN = ROOT / 'results/catalog-breaking-ciliberto-later-controls-20261118/plan.json'


def load_context():
    context = producer.load_plan(LATER_PLAN, later.PLAN_SHA)
    first_plan = first.producer.check(FIRST_INPUTS, first.PLAN_SHA)
    return context, first_plan


def scope(context, first_plan):
    plan, inventory, _, _, _ = context
    original = read(first.producer.SOURCE / 'inventory.json')
    selected = {}
    for bid in original['reusable_verified_branches']:
        selected[bid] = {'stage': 'published', 'partition': None}
    for name, stage_plan in [('diagnostics', first_plan), ('controls', plan)]:
        for part in stage_plan['partitions']:
            for row in part['branches']:
                bid = row['record_id']
                require(bid not in selected, 'A branch appears in multiple evidence stages')
                selected[bid] = {'stage': name, 'partition': part['index']}
    require(len(selected) == 7334 and set(selected) == set(inventory['branches'])
            and len(inventory['cases']) == 74 and len(inventory['generated_potential_branch_ids']) == 200,
            'Complete 7334-branch, 74-case scope is required')
    counts = {name: sum(v['stage'] == name for v in selected.values())
              for name in ('published', 'diagnostics', 'controls')}
    require(counts == {'published': 215, 'diagnostics': 260, 'controls': 6859},
            'Complete original stage allocation differs')
    for bid, row in selected.items():
        row['origin'] = inventory['branch_origins'][bid]
    return {'model_id': inventory['model_id'], 'branches': selected, 'stage_counts': counts,
            'selected_case_keys': sorted(inventory['cases']), 'full_untreated_control': inventory['full_untreated_control'],
            'input_manifest_sha256': producer.MANIFEST_SHA, 'diagnostic_run': dict(first.RUN),
            'diagnostic_plan_sha256': first.PLAN_SHA, 'control_run': dict(later.RUN),
            'control_plan_sha256': later.PLAN_SHA, 'original_model_cases': 622,
            'original_passing_cases': 548, 'full_model_coverage_claimed': False}


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


def published_branch(directory, entry, context, report):
    plan, inventory, _, info, grid = context
    bid = entry['record_id']
    path = directory / (bid + '.json')
    require(entry['file'] == path.name and not path.is_symlink() and digest(path) == entry['sha256'],
            'Published record checksum or path differs')
    record = read(path)
    spec = inventory['branches'][bid]
    require(record['record_id'] == bid and record['specification'] == spec
            and record['fingerprint'] == report['fingerprint'] and record['case_recovery_claimed'] is False
            and set(record['integrations']) == set(LABELS), 'Published branch scope differs')
    times = grid[grid <= spec['stop']]
    trains = [ResetTrain(**t) for t in spec['reset_trains']]
    traces = {}
    for label in LABELS:
        if case_math.check_outcome(record['integrations'][label], label, plan['requests'][label],
                                   times, info['observables'], trains, info['sha256']):
            traces[label] = trajectory(directory, bid, label, record['traces'][label], times, info['observables'])
    require(set(traces) == set(record['traces']), 'Published trajectory inventory differs')
    checks = {a + '_vs_' + b: comparison(traces[a], traces[b], **plan['acceptance'])
              for i, a in enumerate(LABELS) for b in LABELS[i+1:] if a in traces and b in traces}
    status = ('incomplete' if len(checks) != 6 else
              'confirmed' if all(c['passed'] for c in checks.values()) else 'mismatch')
    require(checks == record['comparisons'] and record['status'] == entry['status'] == status,
            'Published comparisons or outcome do not reproduce')
    return {'record_id': bid, 'status': status, 'complete_diagnostic': True, 'verified_arrays': len(traces),
            'record_sha256': entry['sha256'], 'traces': record['traces'], 'comparisons': checks,
            'windows': {label: summarize(t, trial_windows(round((spec['stop'] - 1010.) / 400.)))
                        for label, t in traces.items()}, 'stage': 'published',
            'origin': inventory['branch_origins'][bid], 'evidence_directory': str(directory.resolve())}


def verify_published(directory, context, store):
    source = read(first.producer.SOURCE / 'inventory.json')
    for name, key in [('report.json', 'reused_report_sha256'), ('inventory.json', 'reused_inventory_sha256'),
                      ('audit.json', 'reused_audit_sha256')]:
        require(not (directory / name).is_symlink() and digest(directory / name) == source[key],
                'Pinned published ' + name + ' differs')
    report, saved = read(directory / 'report.json'), read(directory / 'inventory.json')
    expected = source['reusable_verified_branches']
    require(len(report['branches']) == len(expected) == 215
            and {r['record_id'] for r in report['branches']} == set(expected) == set(saved['branches'])
            and report['requests'] == context[0]['requests'] and report['acceptance'] == context[0]['acceptance'],
            'Published branch inventory or numerical requests differ')
    for entry in report['branches']:
        bid = entry['record_id']
        require({k: entry[k] for k in ('file', 'sha256')} == expected[bid]
                and saved['branches'][bid] == context[1]['branches'][bid], 'Published branch selection differs')
        store.add(bid, published_branch(directory, entry, context, report))
    return {'status': 'verified', 'branches': 215, 'directory': str(directory.resolve()),
            'report_sha256': source['reused_report_sha256'], 'inventory_sha256': source['reused_inventory_sha256'],
            'published_audit_sha256': source['reused_audit_sha256']}


def resolve_descriptor(value, parent):
    require(set(value) == {'selection', 'snapshots', 'cache'}, 'Stage evidence paths differ')
    return {name: (parent / path).resolve() for name, path in value.items()}


def verify_stage(name, paths, context, first_plan, input_validation, output, store, *, archive_provider=None, recovery=None):
    """Recheck original ZIPs and complete branch reports; never trust status.json."""
    module = first if name == 'diagnostics' else later
    plan = first_plan if name == 'diagnostics' else context[0]
    selection = read(paths['selection'])
    snapshots = paths['snapshots']
    run, jobs, artifacts = (read(snapshots / (key + '.json')) for key in ('run', 'jobs', 'artifacts'))
    require(jobs['total_count'] == len(jobs['jobs']) == len(plan['partitions']) + 1
            and len({j['id'] for j in jobs['jobs']}) == jobs['total_count']
            and artifacts['total_count'] == len(artifacts['artifacts']), 'Complete unique API inventories are required')
    require(module.bind_selection(plan, run, jobs) == selection, 'Fixed source selection differs')
    preserved = later.preserve_snapshots(paths['selection'], snapshots, output)
    recovery_provenance = None
    if recovery is not None:
        require(name == 'controls', 'Missing-output recovery applies only to later controls')
        recovery.validate_original(selection, run, jobs, artifacts)
        recovery_provenance = recovery.preserve(output)
    script = 'run_ciliberto_full_diagnostics.py' if name == 'diagnostics' else 'run_ciliberto_later_controls.py'
    runner_sha = hashlib.sha256(subprocess.check_output(['git', 'show', module.RUN['head_sha'] +
        ':python/scripts/' + script], cwd=ROOT)).hexdigest()
    pending, errors, partitions = [], [], []
    for row in selection['selected']:
        try:
            replaced = recovery is not None and row['index'] == 43
            selected_module, selected_run, selected_jobs, selected_artifacts = module, run, jobs, artifacts
            selected_cache, selected_runner = paths['cache'], runner_sha
            if replaced:
                row = recovery.row
                selected_module, selected_run = recovery.module, recovery.run
                selected_jobs, selected_artifacts = recovery.jobs, recovery.artifacts
                selected_cache, selected_runner = recovery.paths['cache'], recovery.runner_sha
            job = next(j for j in selected_jobs['jobs'] if j['id'] == row['job_id'])
            selected_module.validate_job(row, selected_run, job)
            if job['status'] != 'completed':
                pending.append({'index': row['index'], 'reason': 'job_' + job['status']})
                continue
            matches = [a for a in selected_artifacts['artifacts'] if a['name'] == row['artifact_name']]
            if not matches:
                pending.append({'index': row['index'], 'reason': 'no_artifact'})
                continue
            require(len(matches) == 1, 'Duplicate selected artifact')
            artifact = matches[0]
            selected_module.validate_artifact(row, selected_run, job, artifact)
            directory = selected_cache / str(selected_run['id']) / 'attempt-1' / f'artifact-{artifact["id"]}'
            archive, evidence = directory / 'download.zip', directory / 'evidence'
            # The original archive index cannot authorize a different producer.
            # A replacement uses its separately declared, checksum-bound cache.
            transport = (archive_provider(name, row, selected_run, artifact) if archive_provider is not None and not replaced
                         else nullcontext((archive, evidence, {})))
            with transport as (archive, evidence, preservation):
                require(archive.is_file() and not archive.is_symlink() and evidence.is_dir()
                        and not evidence.is_symlink() and not archive.parent.is_symlink(), 'Original cached ZIP or evidence is missing')
                require(digest(archive) == artifact['digest'].removeprefix('sha256:')
                        and archive.stat().st_size == artifact['size_in_bytes'], 'Original cached ZIP differs')
                files = first.verify_zip(archive, evidence)
                if name == 'diagnostics':
                    checked = first.verify_partition(evidence, row, FIRST_INPUTS, plan, runner_sha)
                else:
                    checked = selected_module.verify_partition(evidence, row, context, selected_runner, input_validation)
                for branch in checked['branches']:
                    bid = branch['record_id']
                    require(bid in context[1]['branches'], 'Audited branch is outside full scope')
                    windows = {}
                    if branch['complete_diagnostic']:
                        independent = branch['independent_audit']
                        windows = (independent['branches'][0]['windows'] if name == 'diagnostics' else independent['windows'])
                    store.add(bid, {**branch, 'windows': windows, 'origin': context[1]['branch_origins'][bid],
                                   'stage': name, 'partition': row['index'], 'job_id': job['id'],
                                   'job_conclusion': job['conclusion'], 'artifact_id': artifact['id'],
                                   'evidence_directory': str((evidence / bid).resolve())})
                partitions.append({'index': row['index'], 'job_id': job['id'], 'job_conclusion': job['conclusion'],
                    'artifact_id': artifact['id'], 'archive_sha256': artifact['digest'], 'evidence_sha256': files,
                    'complete_selected_diagnostics': checked['complete_selected_diagnostics'],
                    'producer_status': checked['producer_status'],
                    'unverified_checkpoint_files': checked['unverified_checkpoint_files']})
                if preservation:
                    partitions[-1]['archive_preservation'] = preservation
                if replaced:
                    partitions[-1]['recovery_run'] = dict(recovery.binding['recovery_run'])
                    partitions[-1]['original_missing_job_id'] = row['previous']['job_id']
        except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
            errors.append({'index': row['index'], 'error': f'{type(error).__name__}: {error}'})
    result = {'run': dict(module.RUN), 'preserved_api_snapshots': preserved,
              'partitions': partitions, 'pending_partitions': pending, 'verification_errors': errors}
    if recovery_provenance is not None:
        result['missing_output_recovery'] = recovery_provenance
    return result


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


def audit(bundle, sources_path, output, *, archive_providers=None, controls_recovery=None):
    require(not output.exists(), 'Use a new full-case audit directory')
    context, first_plan = load_context()
    selected = scope(context, first_plan)
    validation = producer.inputs.validate(bundle, producer.MANIFEST_SHA)
    source_bytes = sources_path.read_bytes()
    sources = read(sources_path)
    require(set(sources) == {'published', 'diagnostics', 'controls'}, 'Every evidence stage must be declared')
    parent = sources_path.parent
    protected = [bundle.resolve()]
    if sources['published'] is not None:
        protected.append((parent / sources['published']).resolve())
    for name in ('diagnostics', 'controls'):
        if sources[name] is not None:
            paths = resolve_descriptor(sources[name], parent)
            protected.extend(paths[k] for k in ('snapshots', 'cache'))
    recovery = None
    if controls_recovery is not None:
        from scripts.ciliberto_missing_output import Recovery
        require(sources['controls'] is not None, 'The full original controls selection is still required')
        recovery = Recovery(controls_recovery)
        protected.extend(recovery.paths[k] for k in ('snapshots', 'cache'))
    require(not any(output.resolve().is_relative_to(path) for path in protected),
            'Audit output must be outside the input evidence directories')
    output.mkdir(parents=True)
    (output / 'sources.json').write_bytes(source_bytes)
    write(output / 'scope.json', selected)
    write(output / 'input-validation.json', validation)
    branch_directory = output / 'branches'
    branch_directory.mkdir()
    store = BranchStore(branch_directory, context[1])
    stages, errors = {}, []
    for name in ('published', 'diagnostics', 'controls'):
        if sources[name] is None:
            stages[name] = {'status': 'not_supplied'}
            continue
        try:
            if name == 'published':
                stages[name] = verify_published((parent / sources[name]).resolve(), context, store)
            else:
                provider = (archive_providers or {}).get(name)
                options = {'archive_provider': provider} if provider is not None else {}
                if name == 'controls' and recovery is not None:
                    options['recovery'] = recovery
                stages[name] = verify_stage(name, resolve_descriptor(sources[name], parent), context, first_plan,
                                           validation, output, store, **options)
                errors.extend({'stage': name, **e} for e in stages[name]['verification_errors'])
        except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile) as error:
            errors.append({'stage': name, 'error': f'{type(error).__name__}: {error}'})
    missing = sorted(bid for bid, row in store.index.items() if not row['complete_diagnostic'])
    complete = not missing and not errors
    baseline, cases, contradictions = None, {}, []
    if complete:
        reference = read(ROOT / 'results/catalog-repeated' / (context[1]['model_id'] + '.json'))
        config = read(producer.inputs.ORIGINAL / 'shard-0' / (context[1]['model_id'] + '.json'))['configuration']
        baseline, cases = replay(context[1], store, read(bundle / 'original-cases.json'), reference, config)
        contradictions = discrepancies(bundle, store)
    require(sources_path.read_bytes() == source_bytes, 'Evidence source descriptor changed during audit')
    result = {'schema_version': 1, 'model_id': context[1]['model_id'],
              'status': 'verification_failed' if errors else 'incomplete' if not complete else
                        'cases_confirmed' if all(c['passed'] for c in cases.values()) else 'complete_with_failures',
              'complete_selected_control_inventory': complete, 'required_branches': 7334, 'selected_cases': 74,
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
    parser.add_argument('--archive-index', type=Path)
    parser.add_argument('--archive-scratch', type=Path)
    parser.add_argument('--archive-budget-gib', type=int, default=16)
    parser.add_argument('--controls-recovery', type=Path)
    args = parser.parse_args()
    if args.operation == 'check':
        require(not args.output.exists(), 'Use a new scope file')
        context, first_plan = load_context()
        result = scope(context, first_plan)
        result['input_validation'] = producer.inputs.validate(args.inputs, producer.MANIFEST_SHA)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write(args.output, result)
        print({'stage_counts': result['stage_counts'], 'selected_cases': len(result['selected_case_keys']),
               'numerical_integrations_performed': 0})
    else:
        require(args.sources is not None, 'Declare all evidence stages in a sources JSON file')
        providers = None
        if args.archive_index is not None:
            from scripts.archive_release_chunks import ReleaseArchiveProvider
            require(args.archive_scratch is not None, 'Declare a scratch directory for streaming archives')
            provider = ReleaseArchiveProvider(args.archive_index, args.archive_scratch,
                                              max_bytes=args.archive_budget_gib * 1024**3)
            providers = {stage: provider for stage in provider.index}
        result = audit(args.inputs, args.sources, args.output, archive_providers=providers,
                       controls_recovery=args.controls_recovery)
        print({k: result[k] for k in ('status', 'complete_branch_outcomes', 'verified_arrays', 'recovered_selected_cases')})
        sys.exit(1 if result['verification_errors'] else 0)
