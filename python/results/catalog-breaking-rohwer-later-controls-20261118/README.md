# Remaining Rohwer controls, in two fixed batches

This stage computes **all 10,924 remaining controls** for the **123 originally
failed cases** of network 35, BioModel **BIOMD0000000038**
(`Rohwer2000_Phosphotransferase_System`). Together with the separately queued
[750 diagnostic branches](https://github.com/m9h/GRN_ODE/actions/runs/44401097371),
these controls cover all **11,674 required branch specifications**. The original
whole-model result remains **137/260 cases passing** until an independent complete
case audit establishes otherwise.

A branch is one initial-history/intervention/rechallenge combination with a fixed
reset schedule and observation horizon. Each candidate trial needs all eight
matched control combinations to distinguish a history-dependent response from an
ordinary response to the intervention. This stage also retains the full untreated
baseline and all 848 potential controls absent from the original saved search.
Conditional first, second and eligible third intervention paths must ultimately
be recomputed from the verified trajectories, including paths not visited in the
original search. A confirmed branch alone cannot establish case recovery.

## Fixed scope and numerical method

| Batch | Global partition indices | Branches | Requested integrations |
|---|---|---:|---:|
| 0 | 0–255 | 5,548 | 22,192 |
| 1 | 256–511 | 5,376 | 21,504 |
| Total | 0–511 | 10,924 | 43,696 |

Sorted branch identifiers are distributed round-robin across 512 partitions:
172 partitions contain 22 branches and 340 contain 21. The batches are disjoint
and together cover every later control. Each workflow run uses at most 256 matrix
jobs and six hours per job, within the documented
[GitHub Actions limits](https://docs.github.com/en/actions/reference/limits).
At most eight computation jobs run concurrently per batch. Each partition has a
19,200-second computation budget, leaving time for setup and artifact upload.

The hash-pinned original `compute_branch` implementation is unchanged:

| Request | Relative tolerance | Absolute tolerance |
|---|---:|---:|
| libRoadRunner | 1e-13 | 1e-15 |
| libRoadRunner refinement | 5e-14 | 5e-16 |
| SciPy Radau with Jaxkineticmodel RHS and JAX Jacobian | 1e-10 | 1e-12 |
| Radau refinement | 1e-11 | 1e-13 |

All six pairwise comparisons use the original acceptance tolerances,
`rtol=2e-5` and `atol=1e-7`. All 17 observables are retained. The original sample
grid contains up to 221,001 samples through time 2,210, with shorter original
endpoints at 1,410 and 1,810. Reset timing, all sampled values and the complete
observation horizon remain intact. These are SBML model experiments, not new
biological observations.

The largest partition contains 2,800,524,672 bytes of uncompressed numeric array
payload (including four time columns), before archive and report overhead.
Before each branch, the wrapper requires space for all four numeric arrays plus
a 512 MiB margin. Time or disk exhaustion leaves an explicit incomplete result
and the unattempted branch inventory. There is no implicit restart or reuse.

## Reproduction and independent verification

Use the [complete released input bundle](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-rohwer-full-controls-20261118),
whose manifest SHA-256 is
`dd1f300d0fc760743a39d6360cb0aae19ff0ee69a3f6b991aada12493045fe0f`.
It preserves 11,247 original records, 123 original cases, every potential branch,
and explicit original versus generated provenance. The tracked execution plan
pins that inventory, the SBML file, the complete grid, all numerical requests,
source files and dependency versions.

From `python/` in an isolated full clone:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
gh release download kinetics-rohwer-full-controls-20261118 --repo m9h/GRN_ODE \
  --dir /path/to/rohwer-inputs
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/run_rohwer_later_controls.py check \
  --plan results/catalog-breaking-rohwer-later-controls-20261118/plan.json \
  --plan-sha256 571526958023ac93789c4e48924ceb44106e378a1520339569e9bb818e84d98e --inputs /path/to/rohwer-inputs
```

`check` independently reconstructs the complete scope and original case evidence,
checks every released input file, and checks the actual installed numerical
runtime. It performs no integrations. `compute` additionally requires a batch,
global partition index, new output directory and budget. For example, append
`--batch 0 --index 0 --output /path/to/new-partition-0 --budget 19200` to the same
arguments and replace `check` with `compute`.

The parent and child reports bind the batch, global partition, plan, source
revision and workflow run/attempt. Atomic report replacement preserves the last
valid checkpoint. Each completed child is independently audited from all saved
array samples, expected observation times, reset counts, six comparisons and
window summaries. Changed requests, truncated arrays, cross-partition records,
unexpected reuse and incomplete reports are rejected. Honest numerical failures
and disagreements remain explicit; temporary or uncheckpointed files are
retained as unverified evidence.

## Status and limits

This is the execution stage; it does not report case recovery or change
whole-model coverage. Both batch runs and the 750 diagnostic branches must be
collected with their original artifact ZIPs and workflow identities. The eventual
full-case audit must inspect all 11,674 branch outcomes and replay all 123 cases
with the unchanged criteria. Original and recomputed conditional paths must remain
separate. Failure or missing work cannot be discarded to improve the result.

All **118 targeted tests pass**, including **53 new tests**. The new tests also
pass with optional JAX imports blocked. Workflow lint and real complete-input,
model and numerical-runtime checks pass. Tests use synthetic full-grid arrays
and mocked workers to check evidence handling; they do not claim numerical
convergence. See [local validation](local-validation.json). Linux validation is
pending; dispatch identities are recorded separately. The stopped local workers and previously dispatched sources are unchanged.
