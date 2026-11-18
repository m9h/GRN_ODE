# Collect both complete Rohwer control batches

This offline collector verifies **all 10,924 later controls in all 512 fixed
partitions**. It preserves original artifact ZIPs and API responses, independently
checks saved trajectories, and retains numerical failures and unfinished work.
Together with the separate 750-branch diagnostic collection, the eventual
complete-case audit requires **11,674 branch outcomes and all 123 original failed
cases**. The original 137/260 whole-model result remains separate.

The numerical producer, its input plan and dependencies are unchanged. Both runs
use source `0dc31af29f4ff9c5e0e610d7c473cc1382fb7dda`, workflow `423215372`,
and attempt **1**:

| Batch | Fixed run | Validation job | Partitions | Controls |
|---|---|---|---|---:|
| 0 | [44419997278](https://github.com/m9h/GRN_ODE/actions/runs/44419997278) | 135210148117 | 0–255 | 5,548 |
| 1 | [44420020715](https://github.com/m9h/GRN_ODE/actions/runs/44420020715) | 135210227397 | 256–511 | 5,376 |

The execution-plan SHA-256 is
`571526958023ac93789c4e48924ceb44106e378a1520339569e9bb818e84d98e`.
All 848 generated potential controls and the untreated baseline remain required.

## Prepare inputs and API snapshots

Use a full clone of the collector branch and an isolated environment. From
`python/`, install locked dependencies with uv and download the
[complete input bundle](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-rohwer-full-controls-20261118):

```sh
uv sync --locked --extra test --extra jaxkineticmodel
gh release download kinetics-rohwer-full-controls-20261118 --repo m9h/GRN_ODE \
  --dir /path/to/rohwer-inputs
```

Save each fixed run's GitHub API metadata, complete jobs response and complete
artifacts response under its own batch directory:

```text
api/
  batch-0/run.json
  batch-0/jobs.json
  batch-0/artifacts.json
  batch-1/run.json
  batch-1/jobs.json
  batch-1/artifacts.json
```

Jobs and artifacts must include **all pages**, combined under their original
`jobs` or `artifacts` array and `total_count`. A first page of 100 jobs cannot
represent a batch of 257. Refresh snapshots to observe progress, retaining earlier
snapshots. Never substitute a later run attempt for the selected attempt.

## Bind actual job identities

Both exact Linux validation jobs must have succeeded, and all **514 job
identities** must exist: two validation jobs plus 512 uniquely named computation
jobs. Missing pages, queued or failed gates, duplicate IDs, swapped batches,
incorrect partition names and altered source revisions are rejected.

```sh
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/collect_rohwer_later_controls.py bind \
  --plan results/catalog-breaking-rohwer-later-controls-20261118/plan.json \
  --inputs /path/to/rohwer-inputs --snapshots /path/to/api \
  --output /path/to/new-fixed-selection.json
```

Binding reconstructs the complete plan and verifies the model, released canonical
inventory and installed numerical runtime. It records global partition indices,
batch/run identities, actual job IDs, exact branch membership and expected artifact
names. Existing selections cannot be overwritten. Pending gates do not produce
placeholder compute IDs. Binding needs `run.json` and `jobs.json` for both batches;
collection additionally requires both `artifacts.json` files.

## Collect terminal artifacts

Download each selected **original ZIP**, including artifacts from failed or
timed-out jobs, to `artifact-ARTIFACT_ID.zip` in an archive directory. Then use the
matching current API snapshots:

```sh
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/collect_rohwer_later_controls.py collect \
  --plan results/catalog-breaking-rohwer-later-controls-20261118/plan.json \
  --inputs /path/to/rohwer-inputs --selection /path/to/new-fixed-selection.json \
  --snapshots /path/to/api --archives /path/to/original-zips \
  --output /path/to/collection
```

Output must be separate from input directories and source plan/selection files.
Collection performs no network requests, integrations or dispatches. It revalidates
every complete input file and all selected original case records, rebinds both API
job inventories, and checks each terminal artifact against its batch, source,
attempt, job interval, size and server SHA-256. Safe extraction checks every file
against the original ZIP. Cached ZIPs and extracted bytes are rechecked on later
passes.

The original selection and all six API response files are preserved in a
fingerprinted snapshot directory. Different snapshots receive separate
directories. The collector and shared ZIP-verification source hashes are recorded.
Both run IDs remain explicit in `status.json`.

For completed child reports, the independent branch auditor checks every saved
sample, all 17 observables, exact observation times, reset evidence, all six
comparisons and derived window summaries. Branches cannot move between batches
or partitions. Available producer audits must reproduce exactly.

For interrupted children, only complete trajectories recorded in the last valid
checkpoint are verified. A complete branch record without a terminal child report
stays incomplete. A child that finished before its parent timed out can be audited,
with the parent's failure retained. Orphan arrays and exact known temporary
checkpoint files remain **unverified**. Missing evidence is never filled by
inventing values, retrying the solver or importing another attempt.

## Interpret the result

- `complete_selected_diagnostics` requires all 10,924 controls to have every
  requested terminal outcome accounted for. Outcomes may include failed solves.
- `all_10924_controls_confirmed` additionally requires all six comparisons to pass
  for every branch.
- `verified_arrays` counts only arrays independently checked from saved data.
- `pending_indices`, `missing_artifacts` and `collection_errors` distinguish
  unfinished jobs, unavailable evidence and failed verification.
- A successful collector exit can accompany `status: incomplete`; it does not
  mean the computation or scientific audit has finished.

No collector status establishes recovered cases. All 11,674 branch outcomes from
both stages must feed an independent replay of all 123 cases, keeping original and
recomputed conditional paths separate. Numerical requests, sample grids, control
scope and acceptance criteria are unchanged. Continuations need their own
authenticated plans; this collector cannot silently replace a fixed attempt.

## Validation status

Tests use explicitly synthetic arrays on the full 221,001-sample grid. They test
evidence handling and do not establish numerical convergence. Local checks and
the real queued-gate rejection are recorded in
[collector-local-validation.json](collector-local-validation.json) and
[collector-pending-gate-verification.json](collector-pending-gate-verification.json).
All **173 targeted local tests pass**, including **86 new collector tests**.
The new tests also pass with optional JAX imports blocked. Workflow lint and the
real plan/model/runtime check pass. Both real queued gates remain unbound, as
required. Cloud computation and Linux validation remain pending.
