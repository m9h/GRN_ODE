# Ciliberto: all remaining original failed-branch diagnostics

This is the first execution stage of the
[complete 74-case inventory](../catalog-breaking-ciliberto-full-inventory-20261118/README.md).
It selects **all 260 original failed branches** without an existing verified
four-trajectory result. Every selected branch receives two RoadRunner and two
SciPy Radau integrations, for **1,040 complete trajectories**. The later
**6,859 controls and potential continuations**, plus a full 74-case audit, remain
required. Branch diagnostics cannot change the whole-model pass count.

The original network-28 search for **BIOMD0000000697**, the Ciliberto 2003
Cyclin E/Cdk2 timer in the *Xenopus laevis* embryo, contains 270 failed branch
specifications. Ten already have complete verified arrays in the published
[two-case recovery](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-ciliberto-cases-20261118).
Those ten are listed explicitly in [plan.json](plan.json). The new selection
retains all other failures: **249 original output-shape errors and eleven
completed solver disagreements**. These error categories do not establish the
cause of the numerical failure.

## Fixed inputs and numerical work

The wrapper verifies the complete source-inventory hash, the full two-stage
schedule, every original partition report, the captured failed records and the
already reproduced full-array recovery audit. The latter was checked against
all 860 published arrays during preparation. Each excluded branch must have a
confirmed audit entry and the exact recorded checksum. No new branch is excluded
on the basis of its outcome.

The 260 remaining branch identifiers are sorted and distributed over 32 fixed
partitions: four contain nine branches and twenty-eight contain eight. Every
branch retains its original reset schedule, full observation grid and all
20 observables. Original source records are preserved separately. The numerical
producer and independent array auditor are unchanged from the tested prior
implementation; only the selection and execution wrapper are new.

| Request | Relative tolerance | Absolute tolerance |
|---|---:|---:|
| RoadRunner | `1e-13` | `1e-15` |
| RoadRunner refined | `5e-14` | `5e-16` |
| SciPy Radau | `1e-10` | `1e-12` |
| SciPy Radau refined | `1e-11` | `1e-13` |

All six pairwise comparisons use the unchanged acceptance tolerances `2e-5`
and `1e-7`. The plan pins numerical source hashes, installed JaxKineticModel
source hashes, package versions, `pyproject.toml` and `uv.lock`. The model,
calibration, solver requests, original source data and dependency environment
are unchanged.

## Execution and validation

The [cloud workflow](../../../.github/workflows/ciliberto-full-diagnostics.yml)
requires a Linux source/runtime check and all targeted tests before starting
any numerical job. It uses uv, eight concurrent jobs at most, a 19,200-second
per-partition computation budget and a six-hour job limit. Each branch runs in
a separate child process. Complete arrays are independently audited immediately
after the child finishes. Integration errors, completed mismatches, audit errors
and timeouts remain explicit and are included in uploaded evidence.

`execution.json` is saved before work and updated atomically. It records the
actual producer commit, workflow run and attempt, wrapper hash, runtime, fixed
branch selection and every observed outcome. Uploads run after both successful
and failed jobs. Existing output directories are rejected; no automatic retry
or continuation of an interrupted partition is implemented. Any continuation
must first verify the saved selection, lineage and completed arrays.

From `python/`, check all real inputs without numerical integration:

```sh
uv run --locked --extra test --extra jaxkineticmodel python scripts/run_ciliberto_full_diagnostics.py \
  check --inputs results/catalog-breaking-ciliberto-full-diagnostics-20261118 \
  --plan-sha256 7a4f5cc4076de6d47a457220a8321d4b6849433c8eef599736c9c0a3f391f3c2
```

All **85 targeted local tests pass**, including 25 new execution/selection tests,
the complete inventory checks, unchanged numerical diagnostic tests and
independent branch/case audit tests. The real input/runtime check and workflow
lint also pass; [local-validation.json](local-validation.json) records the hashes.
Synthetic worker tests do not establish new scientific results. Linux validation
must pass separately before the cloud computations run.

The local stopped workers are not used. Full artifact collection, fixed-run
assembly and the later complete-case audit remain necessary before any recovery
can be reported. The original whole-model result remains 548/622.

The [offline collection guide](COLLECTION.md) describes the fixed-run collector,
including verification of original ZIPs, full trajectory arrays and interrupted
checkpoints. Its 43 collection tests and 90 combined targeted tests pass locally.
The queued producer remains frozen at `4c58f7969373f447cbb64e6390fceac92548dd31`;
the collector is developed on the separate `kinetics-ciliberto-full-collection`
branch. These checks establish collection behavior, not new numerical results.
