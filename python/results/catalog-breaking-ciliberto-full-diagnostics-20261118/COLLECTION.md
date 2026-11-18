# Collect the fixed Ciliberto diagnostic run

The offline collector requires all **32 fixed jobs and all 260 selected original
failed branches**. It verifies available results, preserves failures and records
unfinished work. It performs no numerical integrations or network requests.
The original whole-model result remains **548/622 cases**. The later **6,859
control branches** and full **74-case audit** remain required.

The producer is frozen at `4c58f7969373f447cbb64e6390fceac92548dd31`, with workflow
[run 44407336593, attempt 1](https://github.com/m9h/GRN_ODE/actions/runs/44407336593).
The fixed plan has SHA-256
`7a4f5cc4076de6d47a457220a8321d4b6849433c8eef599736c9c0a3f391f3c2`.
Collector changes live on a separate branch; the queued producer, numerical
source and stopped workers' environments remain unchanged.

## Bind job identities after validation

Save the GitHub API run and complete jobs responses, retaining all pages and
their total count. Validation job **135165962664** must have completed
successfully at the fixed revision. All 32 named compute jobs must exist exactly
once. A queued or failed gate cannot authorize a fixed selection.

From `python/` in the collector checkout:

```sh
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/collect_ciliberto_full_diagnostics.py bind \
  --inputs results/catalog-breaking-ciliberto-full-diagnostics-20261118 \
  --run /path/to/api/run.json --jobs /path/to/api/jobs.json \
  --output /path/to/new-fixed-selection.json
```

The selection binds every job ID, partition membership and expected artifact
name. Existing selections cannot be overwritten. Another workflow attempt needs
its own explicitly verified continuation plan.

## Download and collect terminal artifacts

Save `run.json`, `jobs.json` and `artifacts.json` from GitHub, including all pages.
Download every selected original ZIP, including evidence from failed or timed-out
jobs, to `artifact-ARTIFACT_ID.zip` in the archive directory. Then run:

```sh
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/collect_ciliberto_full_diagnostics.py collect \
  --inputs results/catalog-breaking-ciliberto-full-diagnostics-20261118 \
  --selection /path/to/new-fixed-selection.json \
  --snapshots /path/to/api --archives /path/to/original-zips \
  --output /path/to/collection
```

Collection verifies the run, attempt, source revision, job identities, artifact
creation times, ZIP sizes and SHA-256 digests. Every extracted file is checked
against its original ZIP; cached files are checked again on later passes.
Missing downloads, pending jobs and verification errors remain explicit in
`status.json`.

Every branch retains its original source partition, failure category,
specification, solver requests, observation grid, model, source hashes and package
versions. Complete reports pass through the unchanged full-array auditor. All
samples, 20 observables, resets and windows remain required. Saved comparisons
and producer audits must reproduce exactly. Solver disagreements and failed
integrations remain failures.

Interrupted diagnostics retain their available evidence. Complete arrays recorded
in checkpoints are verified and compared without declaring the diagnostic
complete. Arrays written before their checkpoint are preserved as unverified.
The frozen producer's exact temporary checkpoint filenames are also retained as
**unverified**, without parsing or using their contents. Unknown filenames are
rejected. A complete child report can be independently audited even if its wrapper
was interrupted; the wrapper's recorded failure remains explicit. No array is
filled from a different attempt.

## Interpret the result

`complete_selected_diagnostics` means all 260 branches have complete reports
accounting for every requested outcome, which may include failed integrations.
`all_260_branches_confirmed` additionally requires every branch to pass all six
pairwise comparisons. `verified_arrays` counts arrays actually checked from saved
evidence. None of these fields establishes case recovery.

The next stage still needs the baseline, complete matched controls, all potential
conditional branches and replay of all 74 original failed cases. Whole-model
coverage must not be updated from diagnostic branch counts.

Local validation passes **43 collector tests and 90 combined producer, collector
and array-auditor tests**. The transport and interruption tests use explicitly
synthetic trajectories on a full original observation grid; they are not new
scientific results. Workflow lint passes. A real input/runtime check passes, and
binding against the actual queued validation job correctly rejects the request
without creating a selection. See [collector-local-validation.json](collector-local-validation.json)
and [collector-pending-gate-verification.json](collector-pending-gate-verification.json).
Linux validation of the collector is pending.
