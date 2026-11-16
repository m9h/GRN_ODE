# Full Fuss case-control validation plan

This experiment extends the [three-branch COPASI/Radau pilot](../catalog-breaking-fuss-radau-plan-20261114/README.md)
to **all 18 originally failed cases** of network 8, **BIOMD0000000069**,
the Fuss 2006 mitotic-activation model. The original result remains **314/332
passing cases** until complete case evidence has been independently audited.

The reconstructed scope contains **1,308 case-control trajectories plus one
full untreated baseline**. Four integrations per trajectory give **5,236
integrations**, with six pairwise full-array comparisons each. This includes
the 330 originally failed branch records and the previously passing controls
used by those same cases. Every possible later conditional control is retained,
including controls that a newly evaluated search might not reach.

The original report, all selected original branches and their provenance are
preserved in this directory. Their source revision is
`70a3afad61357e94873ff62a7300c099b4c7ae3e`. The reconstruction checks every
original branch and case against the historical code, model, calibration and
archived evidence. It reproduces the complete capture, rather than importing
the three pilot branches as if they covered the remaining failures.

## Numerical and scientific checks

The experiment uses the pilot's declared requests:

| Implementation | Relative tolerance | Absolute tolerance |
| --- | ---: | ---: |
| COPASI | 1e-13 | 1e-15 |
| COPASI refined | 5e-14 | 5e-16 |
| SciPy Radau with Jaxkineticmodel equations | 1e-11 | 1e-13 |
| Radau refined | 1e-12 | 1e-14 |

The pointwise acceptance thresholds remain relative **2e-5** and absolute
**1e-7**. The original observation grid, reset trains, absolute clock and full
horizons are unchanged. Four full binary64 arrays are saved for each completed
trajectory. JAX computes the ODE right-hand side and its Jacobian; SciPy performs
the stiff integration. COPASI independently imports and integrates the SBML.
This therefore checks both numerical integration and the shared JAX importer's
interpretation. It does not make the SciPy solve differentiable.

The separate auditor requires every original partition, reads every saved
observation, recomputes all six comparisons and the response-window summaries,
and then replays both primary and refined conditional searches. Case recovery
requires the full untreated baseline, all original and possible controls, and
agreement of the controlled classifications across all four trajectories.
Original, primary and refined search paths remain explicit; near-zero literal
MATLAB direction changes are not hidden by changing the search rule.

The control calculation compares rechallenge minus sham responses in trained
and untrained systems, with and without the breaker. Subtracting the untrained
breaker effect prevents a direct drug-like response from being mistaken for
an effect on prior history. Numerical agreement does not guarantee that a
particular intervention has a resolved history effect.

Previously passing original branch summaries are compared with the new windows;
contradictions are flagged for revalidation. The 314 originally passing cases
are **not** silently added to the new selected-case result. This experiment
cannot by itself claim a passing whole-model recovery.

## Fixed partitions and checkpoints

[execution-plan.json](execution-plan.json) fixes the input hashes, all 18 case
keys, complete 1,309-trajectory inventory, settings and **32 partitions**.
The baseline comes first, followed by sorted branch IDs; each partition takes
every 32nd entry. Partitions have 40 or 41 trajectories and do not overlap.
Selecting a subset for continuation never changes the required full inventory.

Completed arrays are atomic checkpoints. A budget stop between integrations
retains them. An integration interrupted before its full array is saved must
be repeated; this workflow does not claim to resume an internal Radau or COPASI
solver state. Failed attempts remain in each branch record. A resume first
verifies all previously completed arrays, source and dependency hashes,
platform, model, full grid, requests and partition selection.

The GitHub restore helper additionally verifies the parent workflow, job
attempt, artifact identity and original ZIP digest. A live parent run, an
expired or ambiguous artifact, a different source or a corrupt cache cannot
be used as a resume source. Workers require their numerical source to match
the committed producer revision. Keep the checkout and environment unchanged
while any worker or collector is using them.

## Run and audit

From the repository's `python` directory at the committed producer revision:

```sh
uv sync --locked --extra test --extra jaxkineticmodel --extra delay
uv run --locked --extra test --extra jaxkineticmodel --extra delay python \
  scripts/run_scipy_case_partition.py \
  --inputs results/catalog-breaking-fuss-full-case-plan-20261116 \
  --output results/scipy-case-parts/partition-0 --shard-index 0
```

Use each original index 0–31, or dispatch `scipy-case-controls.yml` with
`operation=compute`. The default matrix retains all 32 indices and runs at most
eight concurrently after the test gate passes. The uv lock pins JAX 0.12.0.1
and the modernized Jaxkineticmodel fork. A checkpointed budget stop returns
exit code 75; GitHub uploads its partial evidence even when the job fails.
To continue, select the same original indices and set `resume_run` to their
completed parent run. Failed numerical results never become passing results
merely because a workflow or upload completed.

After collecting all partitions into `results/scipy-case-parts/partition-N`,
run the complete auditor (the short Python wrapper only constructs CLI arguments):

```sh
uv run --locked --extra test --extra jaxkineticmodel --extra delay python - <<'PY'
import subprocess, sys
inputs = [arg for i in range(32) for arg in ('--input', f'results/scipy-case-parts/partition-{i}')]
subprocess.run([sys.executable, 'scripts/audit_scipy_case_partitions.py', *inputs,
                '--output', 'results/scipy-case-parts/audit.json'], check=True)
PY
```

The auditor takes read locks and performs no integration. A complete audit may
still report numerical mismatches, an unresolved case, or a failed baseline;
those outcomes are retained. Unit tests use explicitly synthetic arrays to
exercise these gates; they are not substitutes for the biochemical computation.
