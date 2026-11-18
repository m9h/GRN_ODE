# Execute all remaining Ciliberto controls

This stage selects **all 6,859 later controls**, including the **200 potential
controls absent from the original saved paths**. Each receives two RoadRunner
and two SciPy Radau integrations: **27,436 requested trajectories**. Selection
comes from the fixed complete 74-case inventory and does not depend on outcomes
from the earlier diagnostic stage.

The final experiment still requires all **7,334 branches**: 215 published
branches, 260 first-stage diagnostics and these 6,859 controls. Complete-case
assembly and replay remain required before any new case recovery is claimed.
The original whole-model result remains **548/622**.

## Fixed inputs and mathematics

[plan.json](plan.json) has SHA-256
`d1e73a51b8cc8b7e5ab2f283c5a31de6a09415db8782551e9ec6392d1a5740c0`.
It binds every branch, partition, observation count, source hash, installed
JaxKineticModel source and numerical package version. The
[authenticated input release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-ciliberto-full-controls-20261118)
has manifest SHA-256
`ab3b592ed1d25786ff22e4611331e633caf3d2ba0fa00907e4607d865d235857`.
Every partition verifies that complete input bundle before computation.

The runner calls the unchanged `compute_branch` implementation used by the
published complete-case recovery. It retains all 20 observables, original reset
trains and full observation grids through 1,410, 1,810 or 2,210 time units.

| Request | Relative tolerance | Absolute tolerance |
|---|---:|---:|
| RoadRunner | `1e-13` | `1e-15` |
| RoadRunner refined | `5e-14` | `5e-16` |
| SciPy Radau | `1e-10` | `1e-12` |
| SciPy Radau refined | `1e-11` | `1e-13` |

An independent branch audit reloads every saved sample, verifies trajectory
hashes, grids, observables and reset/segment evidence, and reproduces all six
pairwise comparisons at acceptance tolerances `2e-5` and `1e-7`. Window summaries
use the unchanged case-audit functions. Generated controls retain explicit
provenance and never acquire an invented original result.

## Execution and interrupted work

The sorted branch list is distributed over **256 fixed partitions**, each with
26 or 27 branches. This bounds the uncompressed numeric array payload to about
4 GB per partition, excluding metadata and runtime files. The runner checks free
disk space before every branch, reserving its four full arrays plus a 512 MiB
margin. A disk stop leaves the remaining branches pending.

The [workflow](../../../.github/workflows/ciliberto-later-controls.yml) uses uv and
requires Linux tests, complete input validation and the real source/runtime check
before computing. It allows eight simultaneous partitions, a 19,200-second
computation budget per partition and a six-hour job limit. GitHub documents the
[256-job matrix and six-hour hosted-job limits](https://docs.github.com/en/actions/reference/limits).

Each branch runs in a separate child process. `execution.json` is saved before
work and after each observed outcome. Complete numerical failures remain
distinct from wrapper errors and timeouts. A diagnostic with four accounted-for
outcomes can finish while one or more integrations failed; this does not confirm
the branch. Failed integrations, orphan arrays and interrupted temporary
checkpoints remain explicit in the evidence. Uploads run after both success and
failure.

Existing output directories are rejected. There is no implicit retry or resume.
Any continuation must first bind the original run/attempt, verify the artifacts
and completed arrays, and explicitly select the unfinished work. Neither a
partial partition nor an unverified checkpoint counts toward completion.

## Validate without integrating

Use a full clone so pinned source revisions remain available. From `python/`:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
gh release download kinetics-ciliberto-full-controls-20261118 --repo m9h/GRN_ODE \
  --dir /path/to/full-control-inputs
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/run_ciliberto_later_controls.py check \
  --plan results/catalog-breaking-ciliberto-later-controls-20261118/plan.json \
  --plan-sha256 d1e73a51b8cc8b7e5ab2f283c5a31de6a09415db8782551e9ec6392d1a5740c0 \
  --inputs /path/to/full-control-inputs
```

All **96 targeted local tests pass**, including 35 new runner and array-audit
checks. Synthetic arrays exercise the complete 221,001-point grid, including
last-sample disagreements, missing samples, reset-count errors, explicit solver
failures and interrupted writes. These tests establish execution/audit behavior,
not Ciliberto convergence. The independent real-input/runtime check and workflow
lint also pass. Linux validation must pass separately before numerical jobs run.

The separate [fixed-run artifact collector](COLLECTION.md) now preserves and
checks complete or interrupted evidence across all 256 partitions. Binding the
real compute-job IDs awaits successful Linux validation and the complete job
list. Full-array case assembly and replay using the new input format remain
required. No stopped local numerical worker is used.
