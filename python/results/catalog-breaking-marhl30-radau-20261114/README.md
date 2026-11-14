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
full arrays; 180 pairwise comparisons are recomputed from those arrays by the
existing independent auditor after each partition finishes. These are the
planned totals, not a claim that the computation has finished.

From `python/`, use an isolated environment with the locked project dependencies:

```bash
uv run --locked --extra test python \
  results/catalog-breaking-marhl30-radau-20261114/run_diagnostics.py \
  --output results/catalog-breaking-marhl30-radau-20261114 --prepare-only
MPLBACKEND=Agg uv run --locked python \
  results/catalog-breaking-marhl30-radau-20261114/run_diagnostics.py \
  --output results/catalog-breaking-marhl30-radau-20261114
```

The first command checks provenance and captures the full failure inventory
without integrations. The second runs all four partitions serially and audits
each terminal diagnostic. Repeating it resumes only records with the unchanged
model, source, environment, settings and observation inventory. A per-diagnostic
lock rejects another process attempting the same output.

No case recovery or full-model validation is claimed. Any recovery must also
validate the complete controls and possible later trials, then recompute the
conditional search and classifications. Both the original Linux result and
the separate macOS result (27/38 passing cases) remain preserved.
