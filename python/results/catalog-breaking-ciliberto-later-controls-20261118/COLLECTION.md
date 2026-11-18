# Collect all Ciliberto later controls

The offline collector requires all **256 partitions and 6,859 controls** from
[run 44412503884, attempt 1](https://github.com/m9h/GRN_ODE/actions/runs/44412503884).
It preserves original artifacts and independently checks saved arrays without
performing integrations. The producer remains frozen at
`05232fa83c4be917455dc2d143a11253cb7773e6`; the collector lives on a separate branch.

The full experiment still requires **7,334 branches and replay of 74 cases**,
including the 215 published branches and 260 first-stage diagnostics. No
collector status changes the original whole-model result of **548/622 cases**.
The 200 controls absent from the original saved paths retain their generated
provenance; an original comparison result is never invented for them.

## Bind the complete job list

Linux validation job **135184099103** must succeed at the fixed producer
revision. All 256 named compute jobs must then exist exactly once. Save the run
response and **all pages** of the jobs response. There are 257 jobs including
validation, so a single 100-job page cannot establish a selection.

For example, save the API responses with the GitHub CLI and jq:

```sh
mkdir -p /path/to/api
gh api repos/m9h/GRN_ODE/actions/runs/44412503884 > /path/to/api/run.json
gh api --paginate --slurp \
  'repos/m9h/GRN_ODE/actions/runs/44412503884/attempts/1/jobs?per_page=100' \
  | jq '{total_count: .[0].total_count, jobs: [.[].jobs[]]}' > /path/to/api/jobs.json
```

Use a full clone so the frozen source revision remains available. From `python/`
in the collector checkout, with the locked test and JaxKineticModel extras:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/collect_ciliberto_later_controls.py bind \
  --plan results/catalog-breaking-ciliberto-later-controls-20261118/plan.json \
  --run /path/to/api/run.json --jobs /path/to/api/jobs.json \
  --output /path/to/new-fixed-selection.json
```

Binding rejects pending or failed validation, incomplete pagination, altered
source or attempt identities, duplicate jobs and changed branch membership.
It refuses to overwrite an existing selection. The actual queued gate was
checked locally and correctly rejected; no real compute-job selection has yet
been created. See [collector-pending-gate-verification.json](collector-pending-gate-verification.json).

## Preserve and verify terminal artifacts

Download the complete [input bundle](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-ciliberto-full-controls-20261118)
to a separate directory. Its manifest and all original case inputs are validated
before collection. The complete plan, model, numerical code and runtime must
also match their frozen identities.

Refresh `run.json` and the complete `jobs.json`, and save the complete artifact
list as `artifacts.json` with all pages and its original total count. Download
each selected original ZIP as `artifact-ARTIFACT_ID.zip`, including uploads from
failed and timed-out jobs. Preserve the original ZIP bytes; do not recompress
extracted directories.

```sh
gh api --paginate --slurp \
  'repos/m9h/GRN_ODE/actions/runs/44412503884/artifacts?per_page=100' \
  | jq '{total_count: .[0].total_count, artifacts: [.[].artifacts[]]}' \
  > /path/to/api/artifacts.json
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/collect_ciliberto_later_controls.py collect \
  --plan results/catalog-breaking-ciliberto-later-controls-20261118/plan.json \
  --inputs /path/to/full-control-inputs \
  --selection /path/to/new-fixed-selection.json \
  --snapshots /path/to/api --archives /path/to/original-zips \
  --output /path/to/collection
```

Collection verifies run, attempt, job, source and artifact identities; artifact
creation times; ZIP sizes and SHA-256 digests; and every extracted byte. Cached
evidence is checked again on each pass. Each pass preserves its selection and
API snapshots in a directory named by their combined fingerprint. `status.json`
also records the collector and shared transport source hashes.

Complete child reports pass through the unchanged independent branch auditor.
All saved samples, 20 observables, original grids, resets and solver requests
remain required. All six pairwise comparisons and saved window summaries must
reproduce. Available producer audits must agree exactly. A complete child report
can survive an interrupted wrapper; the wrapper failure remains in the result.

An incomplete branch can contribute verified arrays and comparisons without
becoming a completed diagnostic. Orphan arrays and the producer's exact temporary
checkpoint filenames remain unverified. Truncated temporary JSON is never
parsed. A finished branch record without its terminal child report remains
incomplete. Unknown files and cross-attempt reuse claims are rejected. There is
no automatic retry, resume or replacement of failed outcomes.

## Read the status without overstating coverage

| Field or status | Meaning |
|---|---|
| `complete_selected_diagnostics` | Every one of the 6,859 controls has a terminal report accounting for all four requested outcomes, including explicit integration failures |
| `all_6859_controls_confirmed` / `controls_confirmed` | Every control also passes its independent numerical comparisons |
| `complete_with_numerical_failures` | All requested outcomes are accounted for, but some controls fail |
| `verified_arrays` | Saved arrays actually checked from available evidence |
| `incomplete` | Pending jobs, missing artifacts or unfinished branches remain |
| `verification_failed` | At least one identity, transport or evidence check failed |

No value establishes case recovery. Complete-case assembly and replay remain
required across all three sources of branches, with generated controls kept
distinct from observed original records. Missing work stays in the inventory.

All **39 collector tests and 117 combined targeted tests pass** locally, along
with workflow lint. The tests use explicitly synthetic arrays on full original
observation grids; they establish collector behavior, not biochemical
convergence. The separate real plan/model/runtime check also passes. Linux
validation remains pending. Validation details are recorded in
[collector-local-validation.json](collector-local-validation.json).
