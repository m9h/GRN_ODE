# Complete Rohwer case audit

This program independently verifies the evidence needed to replay **all 123
originally failed cases** of network 35, BioModel **BIOMD0000000038**
(`Rohwer2000_Phosphotransferase_System`). It requires **all 11,674 distinct branch
outcomes**, including the untreated baseline and 848 generated potential controls.
It performs no integrations and changes no numerical methods or case criteria.

The original native-solver audit remains **137/260 cases passing**. This auditor
handles the 123 failed cases separately; it does not add recovered cases to the
137 or claim passing whole-model coverage. These are tests of model behavior under
the original intervention protocol, not new biological observations.

## Why the complete control inventory matters

Each candidate intervention has eight matched combinations of prior stimulation,
intervention and rechallenge. Their responses help distinguish a change associated
with stimulation history from an ordinary response to the intervention. The
unchanged source algorithm conditionally tries a second intervention and eligible
third interventions according to the responses seen so far.

The audit replays that search separately for the primary RoadRunner/Radau pair
and their tolerance refinements, retaining the original recorded path for
comparison. All possible controls remain required even if a recomputed path
stops early. A failed baseline, unconfirmed potential control, unresolved search
or failed classification check prevents case recovery under the existing rules.
The report keeps path agreement separate from case passage, matching the original
evaluator's treatment of raw responses near zero.

## Required evidence

| Stage | Fixed run, attempt 1 | Required branches |
|---|---|---:|
| Original failed-branch diagnostics | [44401097371](https://github.com/m9h/GRN_ODE/actions/runs/44401097371) | 750 |
| Later controls, batch 0 | [44419997278](https://github.com/m9h/GRN_ODE/actions/runs/44419997278) | 5,548 |
| Later controls, batch 1 | [44420020715](https://github.com/m9h/GRN_ODE/actions/runs/44420020715) | 5,376 |
| Complete case scope | Three fixed runs | 11,674 |

Diagnostics use producer revision `40fe82344d8dacb2d79ebdc4087ee52beb90a091`.
Both control batches use `0dc31af29f4ff9c5e0e610d7c473cc1382fb7dda`.
The complete [released input bundle](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-rohwer-full-controls-20261118)
has manifest SHA-256
`dd1f300d0fc760743a39d6360cb0aae19ff0ee69a3f6b991aada12493045fe0f`.
It preserves the original case records, all 11,247 selected original branch records
across partitions, full specifications and explicit observed/generated provenance.

Prepare the collections using the
[750-branch collection guide](../catalog-breaking-rohwer-diagnostics-20261118/COLLECTION.md)
and the [two-batch control guide](../catalog-breaking-rohwer-later-controls-20261118/COLLECTION.md).
Retain their exact selections, all API pages, original ZIPs and extracted evidence.
The full-case auditor rechecks these sources; it never accepts a collector's
`status.json` as proof that a branch passed.

## Reproduce the scope check

Use a full clone and an isolated environment. From `python/`:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
gh release download kinetics-rohwer-full-controls-20261118 --repo m9h/GRN_ODE \
  --dir /path/to/rohwer-inputs
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/audit_rohwer_full_cases.py check \
  --inputs /path/to/rohwer-inputs --output /path/to/new-scope.json
```

This checks both execution plans, source and dependency identities, the SBML
model, complete original input evidence, all selected case keys, the shared
numerical requests, and the disjoint assignment of every required branch. The
baseline and all 848 generated controls must belong to the later-control stage.
The original full observation grid and all 17 observables remain required.

## Audit available evidence and replay complete cases

Create a source descriptor with both stages declared. Paths are relative to that
JSON file unless absolute:

```json
{
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

The control snapshots contain both `batch-0/` and `batch-1/`; diagnostics use the
original flat API layout. A stage that is not yet available must be explicitly
`null`. Missing stages leave their branches pending and prevent case replay.

```sh
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/audit_rohwer_full_cases.py audit \
  --inputs /path/to/rohwer-inputs --sources /path/to/sources.json \
  --output /path/to/new-full-case-audit
```

Every invocation needs a new output directory outside input evidence. The audit
preserves the source descriptor and original API response bytes, binds exact
runs/jobs/attempts, verifies ZIP hashes and every extracted byte, and invokes the
independent branch auditors. Every saved array sample, expected observation time,
observable, reset, solver outcome, pairwise comparison and window summary is
checked. Both primary and refined requests must match across stages.

Interrupted work and explicit numerical failures remain distinct. A verified
terminal failed solve accounts for an outcome but cannot produce a passing branch.
Partial or uncheckpointed arrays do not supply completed outcomes. Parent-job
failures remain in provenance even when a child finished before interruption.
Existing strict diagnostic-format checks are retained; malformed or unsupported
partial evidence becomes a verification error, not an invented completion.

The auditor stores branch summaries on disk with a bounded cache, then requires
all 11,674 terminal branch outcomes and no verification errors before replaying
all 123 cases through the unchanged `evaluate_case` implementation. Original,
primary and refined paths remain visible. Contradictions with previously passing
original window summaries are reported with their original partition identities;
this does not claim cross-run agreement of unavailable original arrays.

Outputs include `scope.json`, `input-validation.json`, preserved API snapshots,
per-branch audits, `branch-index.json` and `audit.json`. A successful process exit
can still report `status: incomplete`. Only the audit's complete scope and case
results establish what was verified. `full_model_coverage_claimed` remains false.

## Validation and current limits

All **235 targeted tests pass**, including **38 new full-case audit tests**. The
new tests also pass with optional JAX imports blocked. Synthetic full-grid arrays
exercise both diagnostic formats, ZIP/API identity, altered final samples,
truncation, reset/request changes and partial outcomes. Synthetic control cubes
exercise the original conditional search and scoring rules; they are not evidence
of numerical convergence in this BioModel.

The real complete-input scope check and an audit with explicitly unavailable
cloud sources are recorded in [local-validation.json](local-validation.json).
That audit must retain all 11,674 branches as pending and recover zero cases.
Actual cloud trajectories and the complete 123-case replay remain outstanding.
Linux validation is pending. No stopped local worker, queued producer or numerical
environment is modified by this work.
