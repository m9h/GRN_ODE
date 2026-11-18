# Rohwer: all failed breaking branches

The completed Linux inventory for **network 35, BIOMD0000000038** (Rohwer2000
phosphotransferase system) covers all 260 initial cases. Its original audit
passes 137 cases and retains 123 failures and 136 unresolved conditional
decisions. This diagnostic preserves that result and selects **all 750 distinct
failed branches** from all sixteen original partitions. It is a prerequisite
for the complete-case work, not a case recovery or a passing model audit.

A fresh source audit rechecked each original ZIP and extracted file, historical
producer identity, branch/case archives and conditional decisions. The complete
whole-model result reproduces exactly, apart from extraction paths.
`source-verification.json` records the sixteen immutable run/job/artifact
identities and checksums. Each `source-partition-NN.json` retains its original
report and every failed branch, including the partition with no failures.
No original report, numerical source or environment was changed.

## What needs diagnosis

The captured failures comprise 466 completed RoadRunner/COPASI disagreements
and 284 records with COPASI output-shape errors. All 750 branch identities are
distinct. The fixed 32-partition plan assigns each once, with 23 or 24 branches
per job. Its SHA-256 is
`ab0f50d411a929a887fdf5132958502ec11a2af620cd577b8fc40f5994b4b9f0`.

The earlier [paired-exposure Radau work](../catalog-paired-scipy-rohwer/report.json)
resolved that experiment's failed trajectories. That motivates checking the same
solver requests here; it does not establish convergence for these longer breaking
protocols. This run uses the existing numerical producer and independent auditor:

| Integration | Relative tolerance | Absolute tolerance |
|---|---:|---:|
| RoadRunner | 1e-13 | 1e-15 |
| Refined RoadRunner | 5e-14 | 5e-16 |
| SciPy Radau, Jaxkineticmodel equations/JAX Jacobian | 1e-10 | 1e-12 |
| Refined Radau | 1e-11 | 1e-13 |

All six pairwise comparisons must pass the original pointwise acceptance
criterion, relative **2e-5** and absolute **1e-7**, across every saved observable
and observation. No acceptance tolerance is relaxed. All four arrays are saved,
checksummed and independently reloaded to recompute comparisons and window
summaries. The two refinement requests test sensitivity to integration accuracy;
cross-engine agreement also checks distinct numerical implementations.

All original resets, endpoint conventions and post-reset observations remain.
728 branches require 221,001 observations through time 2210; eleven require
141,001 through 1410 and eleven require 181,001 through 1810. Four integrations
per branch mean **3,000 requested trajectories**, with 17 observables each.

## Validation and execution

Local validation passes **44 targeted tests**, including altered/missing
selections, changed source hashes and requests, mismatches, timeouts, process
failures and audit failures. The complete real input check and `actionlint` pass.
No Rohwer integration was performed during capture or these input checks.
Linux validation must pass before any of the 32 cloud computation jobs starts.
Use uv with the unchanged locked environment:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/run_rohwer_breaking_diagnostics.py check \
  --inputs results/catalog-breaking-rohwer-diagnostics-20261118 \
  --plan-sha256 ab0f50d411a929a887fdf5132958502ec11a2af620cd577b8fc40f5994b4b9f0
```

The workflow `.github/workflows/rohwer-breaking-diagnostics.yml` limits concurrent
jobs to eight. Each gets 19,200 seconds of integration budget and always uploads
its execution record and available raw evidence. A timeout or mismatch produces
a nonzero exit and remains explicit. Existing output directories are rejected;
any continuation must first verify and preserve the previous evidence.
The execution record binds the fixed plan, partition, source revision, workflow
run/attempt, package versions, source hashes and every attempted branch.

## Remaining full-scope work

After every selected attempt finishes, collect the original artifact ZIPs and
verify all 750 identities and full arrays. Passing branch diagnostics alone do
not resolve any of the 123 failed cases. Those cases still require the untreated
baseline, all matched controls and all potentially required conditional branches,
including candidates skipped by the original failed search. Recompute the
conditional decisions and controlled response classifications from that complete
evidence before changing any whole-model count. Keep numerical agreement
separate from whether the model exhibits a resolved history effect.

The nine original local numerical workers remain stopped. This preparation and
the cloud workflow do not resume them or alter their source trees.

The separate [offline collection guide](COLLECTION.md) explains fixed job binding,
original ZIP verification, full-array audits and preservation of interrupted work.
