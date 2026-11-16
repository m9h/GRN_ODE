# Marhl full-horizon breaking diagnostic

The original four-partition Linux search evaluates all 38 initial breaking
cases in BioModel 39, the Marhl calcium-oscillation model. It validates 26 cases
and retains 12 mismatches. All 171 conditional trials finish. This is separate
from the shorter paired-learning experiment, whose arbitrary-precision checks
do not validate these longer trajectories.

This diagnostic covers every failed branch in that Linux search: 30 branch
records across four partitions, representing 29 distinct specifications. One
shared failed control appears in two partitions; both original records and
their separate diagnostics are retained. The original full-model audit is
rerun before capture. `plan.json` binds the reports, partition manifests and
all captured failures; `source-partition-*.json` preserves their original
comparison results and exact intervention schedules.

For each record, the computation retains its original 0.01 observation grid,
complete horizon (1410, 1810 or 2210 time units), every observable and every
reset. RoadRunner uses relative/absolute tolerances `1e-14/1e-16`, refined to
`5e-15/5e-17`; SciPy Radau uses `1e-11/1e-13`, refined to `1e-12/1e-14`.
The acceptance thresholds remain `2e-5/1e-7`. All 120 integrations save their
full arrays. All 120 integrations and all four partition audits have finished;
the auditor recomputes 180 pairwise comparisons from the saved arrays.

## Completed result

| Partition | Branch records | All six comparisons pass |
|---|---:|---:|
| 0 | 1 | 1 |
| 1 | 6 | 1 |
| 2 | 22 | 0 |
| 3 | 1 | 1 |
| Total | 30 | 3 |

The passing control in partitions 0 and 3 is the same specification. Thus these
are 3 confirmed records out of 30, or 2 distinct confirmed specifications out
of 29. All 27 mismatching records and their trajectories are retained.

Radau agrees with its tighter run on 25/30 records; RoadRunner does so on 3/30.
The two refined solvers agree on 5/30. Passing one of these comparisons does
not satisfy the required six-comparison rule. These results identify remaining
numerical uncertainty over the full horizons; they do not establish that either
solver is correct on the unresolved trajectories. The shorter paired-learning
high-precision result cannot be extrapolated to this experiment.

No case has been recovered. The original Linux result stays at 26/38 passing
cases, with the separate macOS result at 27/38. Full controls, all possible later
trials and a fresh conditional-search audit are still required for recovery.

## Audit the released arrays

The [data release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-marhl-breaking-radau-20261116)
contains `catalog-breaking-marhl30-radau-20261114.tar.gz` and `SHA256SUMS`.
All 120 NPZ trajectories, four reports and audits, captured original evidence,
the predeclared plan and per-file checksums are included. Use the release tag's
checkout: its numerical implementation matches revision
`47038da16bac36d7190bc2d428d13f09f01e1bc6`.

From that checkout's `python/` directory:

```bash
gh release download kinetics-marhl-breaking-radau-20261116 --repo m9h/GRN_ODE --dir /tmp/marhl-radau-release
(cd /tmp/marhl-radau-release && shasum -a 256 -c SHA256SUMS)
tar -xzf /tmp/marhl-radau-release/catalog-breaking-marhl30-radau-20261114.tar.gz -C /tmp/marhl-radau-release
(cd /tmp/marhl-radau-release/catalog-breaking-marhl30-radau-20261114 && shasum -a 256 -c SHA256SUMS)
uv sync --locked --extra jaxkineticmodel
for partition in 0 1 2 3; do
  uv run --locked --extra jaxkineticmodel python scripts/audit_scipy_breaking.py \
    --input /tmp/marhl-radau-release/catalog-breaking-marhl30-radau-20261114/shard-$partition \
    --output /tmp/marhl-radau-release/recomputed-audit-$partition.json
  cmp /tmp/marhl-radau-release/recomputed-audit-$partition.json /tmp/marhl-radau-release/catalog-breaking-marhl30-radau-20261114/shard-$partition/audit.json
done
```

This verifies all original sample grids and reset counts and recomputes the
comparisons without integrations. A successful audit means the recorded results
are reproducible; the audit retains the 27 numerical mismatches.

## Repeat the integrations

From `python/`, use an isolated environment with the locked project dependencies:

```bash
uv run --locked --extra test --extra jaxkineticmodel python \
  results/catalog-breaking-marhl30-radau-20261114/run_diagnostics.py \
  --output results/catalog-breaking-marhl30-radau-20261114 --prepare-only
MPLBACKEND=Agg uv run --locked --extra jaxkineticmodel python \
  results/catalog-breaking-marhl30-radau-20261114/run_diagnostics.py \
  --output results/catalog-breaking-marhl30-radau-20261114
```

The first command checks provenance and captures the full failure inventory
without integrations. The second runs all four partitions serially and audits
each terminal diagnostic. Repeating it resumes only records with the unchanged
model, source, environment, settings and observation inventory. A per-diagnostic
lock rejects another process attempting the same output.

Use a fresh output directory to repeat the integrations. The retained
`execution.json` records the original launch, not current process status.
