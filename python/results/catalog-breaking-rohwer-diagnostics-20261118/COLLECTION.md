# Collect the fixed Rohwer run

The offline collector requires all **32 fixed jobs and all 750 original failed
branches**. It preserves numerical failures and incomplete attempts, independently
audits every available completed diagnostic and records the remaining work.
It does not perform integrations, make network requests, dispatch jobs or promote
branch results into recovered cases. The original 137/260 model result remains.

The producer is frozen at `40fe82344d8dacb2d79ebdc4087ee52beb90a091`, with workflow
[run 44401097371, attempt 1](https://github.com/m9h/GRN_ODE/actions/runs/44401097371).
The fixed plan has SHA-256
`ab0f50d411a929a887fdf5132958502ec11a2af620cd577b8fc40f5994b4b9f0`.
The collector lives on a separate branch; it does not modify the queued producer,
the original numerical code or the stopped workers' environments.

## Bind job identities after validation

Save the GitHub API run and complete jobs responses, including every page.
The validation job must be **135144005920**, completed successfully at the fixed
source revision. All 32 named compute jobs must then exist exactly once. The
collector rejects a queued or failed gate and cannot bind a partial job list.

```sh
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/collect_rohwer_breaking_diagnostics.py bind \
  --inputs results/catalog-breaking-rohwer-diagnostics-20261118 \
  --run /path/to/api/run.json --jobs /path/to/api/jobs.json \
  --output /path/to/new-fixed-selection.json
```

The new selection binds every job ID, partition membership and expected artifact
name. Existing selections cannot be overwritten. A later workflow attempt needs
its own explicitly verified continuation plan; it cannot replace this attempt's
results silently.

## Download and collect terminal artifacts

Save `run.json`, `jobs.json` and `artifacts.json` from GitHub, retaining all pages
and their total counts. Download each selected original ZIP to
`artifact-ARTIFACT_ID.zip` in an archive directory. Include artifacts from failed
or timed-out jobs. Then run:

```sh
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/collect_rohwer_breaking_diagnostics.py collect \
  --inputs results/catalog-breaking-rohwer-diagnostics-20261118 \
  --selection /path/to/new-fixed-selection.json \
  --snapshots /path/to/api --archives /path/to/original-zips \
  --output /path/to/collection
```

Collection checks run, attempt, source, job identity, artifact creation time,
ZIP size and SHA-256. It safely extracts nested files and verifies every extracted
byte against the original ZIP. Cached files are rechecked on subsequent passes.
Missing downloads, pending jobs and verification errors remain separate in
`status.json`.

Every branch must match its original captured partition, specification, requests,
observation grid, model, numerical source and package versions. Completed reports
are passed through the unchanged full-array auditor; saved comparisons and any
producer audit must reproduce exactly. Every sample, observable, reset and window
remains required. Honest mismatches and explicit failed integrations stay failed.

For interrupted diagnostics, complete arrays already recorded in their checkpoints
are verified and compared, but the diagnostic remains incomplete. An array written
before its checkpoint was saved is preserved as **unverified**, with no completion
claim. If the child finished its report before the wrapper was interrupted, the
collector can independently audit that complete report while retaining the wrapper's
recorded failure. It never fills a missing array from a different attempt.

## Interpret the result

`complete_selected_diagnostics` means all 750 branches have complete reports with
all requested outcomes accounted for. Some outcomes may be failed integrations.
`all_750_branches_confirmed` additionally requires all six comparisons to pass for
every branch. `verified_arrays` counts only arrays actually checked from saved
evidence; neither status implies case recovery.

The next scientific step still requires the baseline, complete matched controls,
all potentially needed conditional branches, and replay of the 123 original failed
cases. Do not update whole-model coverage from this collector's branch counts.

The transport and interruption tests use clearly marked synthetic trajectories on
an original full observation grid. They test collection behavior, not convergence
of the Rohwer model. Real cloud results remain pending.

Local validation passes 34 collector tests and 78 combined producer, collector
and full-array-auditor tests. Workflow lint passes. A check against the real
queued validation job correctly rejects binding and creates no selection;
`collector-pending-gate-verification.json` records the input snapshot hashes.
Linux validation of the collector is pending.
