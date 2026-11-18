# Replay all 74 original failed Ciliberto cases

The full-case auditor joins **all 7,334 required branches** before replaying the
74 originally failed cases with the unchanged case-scoring functions. It checks
original artifact bytes and saved observations, performs no integrations, and
writes a new audit directory. It cannot turn a partial collection into a case
recovery.

| Evidence source | Required branches | Fixed identity |
|---|---:|---|
| Published two-case recovery | 215 | [Evidence release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-ciliberto-cases-20261118); report, inventory, audit and record hashes pinned by the complete inventory |
| Original failed-branch diagnostics | 260 | [Run 44407336593](https://github.com/m9h/GRN_ODE/actions/runs/44407336593), attempt 1, source `4c58f79` |
| All remaining controls | 6,859 | [Run 44412503884](https://github.com/m9h/GRN_ODE/actions/runs/44412503884), attempt 1, source `05232fa` |

The complete untreated baseline is included among the published branches. The
200 potential controls absent from the original saved paths remain explicitly
generated controls, without invented original outcomes. The original model
result is still **548/622 cases**. This audit selects the other 74 cases; it does
not add their results to 548 or claim a new whole-model total.

## What is recomputed

The input adapter reproduces all original selected records and generates the
complete potential-control inventory from the original case plans. Both producer
plans, numerical source hashes, installed numerical runtime, SBML model,
calibration and observation grid must match their frozen identities.

For published branches, the auditor checks the pinned reports and records, then
reloads all four arrays, checks every sample and observable, verifies requests and
reset evidence, and recomputes all six pairwise comparisons and window summaries.
For each cloud partition, it revalidates the complete job selection and API pages,
original ZIP checksum and size, every extracted byte, producer report and full
branch audit. A collector's `status.json` is never accepted as a substitute for
these checks. Failed jobs can contain complete child results; their wrapper
failure remains in the evidence.

The existing `evaluate_case` function replays the primary RoadRunner/Radau pair
and the refined pair separately, using every required matched control. Original,
primary and refined conditional paths are recorded separately. A disagreement
near a raw reversal boundary is reported using the existing rules; the auditor
does not change the scoring thresholds or choose a favorable path.

Every branch must have an independently checked terminal outcome before the
74-case replay begins. Explicit integration failures count as accounted-for
outcomes, and prevent affected cases from passing. Pending branches and partial
checkpoints keep the complete audit unfinished. Complete-case recovery also
requires a passing untreated baseline, agreement across all original and
potential controls, and the original controlled-classification checks.

Contradictions between new window summaries and originally passing branch
summaries are reported separately, retaining each original partition's identity.
These comparisons do not establish agreement between historical raw arrays:
the original archives did not preserve those arrays.

## Check the complete scope

Use a full clone and an isolated environment. From `python/`:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
gh release download kinetics-ciliberto-full-controls-20261118 --repo m9h/GRN_ODE \
  --dir /path/to/full-control-inputs
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/audit_ciliberto_full_cases.py check \
  --inputs /path/to/full-control-inputs --output /path/to/new-scope.json
```

This validates all original inputs and the exact 215 + 260 + 6,859 allocation
without reading new simulation results or performing numerical integrations.

## Audit available evidence

First use the [diagnostic collector](../catalog-breaking-ciliberto-full-diagnostics-20261118/COLLECTION.md)
and [later-control collector](../catalog-breaking-ciliberto-later-controls-20261118/COLLECTION.md)
to bind the actual job IDs after validation and preserve terminal artifacts.
Declare every source in a JSON file. Relative paths resolve from that file's
directory:

```json
{
  "published": "published-complete-case-evidence",
  "diagnostics": {
    "selection": "diagnostics/selection.json",
    "snapshots": "diagnostics/api",
    "cache": "diagnostics/collection"
  },
  "controls": {
    "selection": "controls/selection.json",
    "snapshots": "controls/api",
    "cache": "controls/collection"
  }
}
```

Each API directory contains the complete `run.json`, `jobs.json` and
`artifacts.json` responses. Each cache is the collector output containing
`RUN_ID/attempt-1/artifact-ARTIFACT_ID/download.zip` and its verified `evidence/`.
Use `null` for an unavailable stage; this keeps its entire required scope pending.
Do not bind placeholder job IDs while a validation gate is queued.

```sh
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/audit_ciliberto_full_cases.py audit \
  --inputs /path/to/full-control-inputs --sources /path/to/sources.json \
  --output /path/to/new-case-audit
```

The output must be new and outside the source evidence directories. Full window
summaries are stored once per branch on disk, with a bounded 64-branch read cache
for case replay. This avoids holding all 7,334 full summaries in memory and does
not duplicate the large trajectory arrays. Keep the original input bundle,
published release, ZIPs, API snapshots and source descriptor with the audit for
reproduction. The audit directory alone is not a complete evidence release.

## Interpret the output

`scope.json` records all required cases, branches, origins and source allocations.
`branch-index.json` records hashes and completion state of the individual saved
branch audits. Exact source and API snapshots are preserved. `audit.json` records
verification errors, missing branches, solver failures, case replay results and
the code hashes used.

| Status | Meaning |
|---|---|
| `incomplete` | Required branches lack terminal audited outcomes; the case map is empty and no recovery is claimed |
| `verification_failed` | At least one source, artifact or evidence check failed; case recovery remains unproven |
| `complete_with_failures` | Every outcome is accounted for and all 74 cases were replayed, but at least one case failed |
| `cases_confirmed` | All 74 selected cases pass; the other 548 cases remain outside this full-array audit |

There is no automatic retry or cross-attempt substitution. If a fixed run stops
partway, its unfinished branches remain required. Any continuation needs an
explicit authenticated source plan before it can join this audit.

Tests use synthetic arrays and control cubes to verify full scope, corrupted or
truncated evidence, failed wrappers, missing final controls, original-path
preservation and unchanged case scoring. Those tests are not biochemical results.
The real input/runtime check and published-evidence check are recorded separately
in [local-validation.json](local-validation.json).

Local validation passes **35 new tests and 137 combined targeted tests**. The
35 new tests also pass with optional JAX packages deliberately unavailable.
Workflow lint and the real complete-input/runtime check pass; Linux validation
is pending.

The real published-data check reloads all **215 branches and 860 trajectories**.
Replaying the two previously published cases from these newly verified summaries
reproduces their existing results exactly. This is a regression check, not a new
recovery claim. With both new stages unavailable, the complete auditor correctly
reports **7,119 branches still required**, an empty case map and zero recovered
cases. See [published-regression-verification.json](published-regression-verification.json).
