# Ueda: complete the four outstanding cases in the cloud

Ueda's Drosophila circadian-clock model, **BIOMD0000000022** (network 11), has a
complete original 302-case search with 298 validated cases. This continuation
retains all four remaining cases and all **323** distinct control trajectories
in the [original complete-case plan](../catalog-breaking-ueda11-case-plan-20261114/README.md).
The local worker remains stopped at the user's request; its directory and
environment have not been changed.

## Evidence preserved before continuation

A separate snapshot preserves every available file: **787 files, 10,102,672,242
bytes**. Each copy was compared to its source by SHA-256. The saved producer
report lists 171 completed branches, but 14 of those records and three arrays
from another completed record are absent. One additional record is unfinished.
The reason for the absent files is unknown; a saved completion label is not
substituted for missing trajectory evidence.

The independent inspection reads every available saved observation, checking
model identity, all observables, time grids, complete reset schedules, requests,
and array hashes. It confirms **156 complete branches** and their **936** pairwise
comparisons. Four additional available arrays belong to two incomplete evidence
sets, giving **628 verified arrays** in total. All original files, including the
partial records, remain in the snapshot.

The [published Ueda Radau diagnostic](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-ueda-radau-20261114)
supplies another verified source for 24 branches. A fresh download verifies all
124 archive members and reproduces its original full-array audit. Importing all
24 through the original producer recreates every previously reported imported
record byte for byte; two missing reported records are restored this way.
Ten imported branches overlap the 156 preserved complete branches, leaving
**170 distinct complete branches** available before new computation.

`preserved-audit.json`, `restoration-proof.json` and `preservation-manifest.json`
record these checks. Preparation performs **no ODE integrations** and claims no
complete case recovery. Full raw snapshot packaging will accompany the final
evidence release; the small files here do not replace the raw arrays.

## Fixed remaining work and mathematical checks

`continuation-plan.json` selects **all 153 remaining branches**, including missing
earlier evidence, the interrupted branch, the untreated baseline and later
candidate branches required by the conditional search. The selection is the
original inventory minus verified complete preserved or published evidence;
numerical pass/fail outcomes do not select branches. Thirty-two disjoint
partitions each compute four or five branches: **612 new integrations** total.

Each branch retains RoadRunner at `(rtol, atol) = (1e-14, 1e-16)` and
`(5e-15, 5e-17)`, plus SciPy Radau at `(1e-11, 1e-13)` and `(1e-12, 1e-14)`.
All six pairwise comparisons use the original condition

```text
abs(x - y) <= 1e-7 + 2e-5 * max(abs(x), abs(y))
```

at every saved sample and observable. The original observation grid, reset
trains and trial horizons remain unchanged; the longest trajectory reaches
time 2210 with 221,001 observations. This checks numerical agreement. The final
case auditor must additionally reconstruct controls, replay all conditional
decisions and compare response classifications across both solvers and their
refinements. The model remains **298/302 validated cases** until that audit.

All thirteen recorded repository numerical-source hashes and five installed
Jaxkineticmodel source hashes match the original producer. Package versions are
checked before any cloud integration. Only new preparation/execution wrappers,
tests, workflow and evidence files are added. The original numerical modules,
`pyproject.toml` and `uv.lock` remain unchanged. New outputs record their cloud
platform, source revision, workflow attempt and exact fixed partition; they
are not represented as byte-identical restorations.

## Reproduce the preparation

Use this source revision with its locked uv environment. With the preserved
snapshot and its manifest available, download the diagnostic release and run:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
gh release download kinetics-ueda-radau-20261114 --repo m9h/GRN_ODE \
  --pattern ueda-radau-20261114.tar.gz --pattern release-manifest.json --dir /path/to/downloads
uv run --locked --extra test --extra jaxkineticmodel python scripts/prepare_ueda_continuation.py \
  --snapshot /path/to/observed-source --manifest /path/to/preservation-manifest.json \
  --inputs results/catalog-breaking-ueda11-case-plan-20261114 \
  --archive /path/to/downloads/ueda-radau-20261114.tar.gz \
  --release-manifest /path/to/downloads/release-manifest.json --output /path/to/new-preparation
uv run --locked --extra test --extra jaxkineticmodel python scripts/continue_ueda_cases.py \
  --inputs results/catalog-breaking-ueda-continuation-20261118 \
  --plan-sha256 4bdd6c344573dac23ba5007e3587c19a2fe6f2839f5972a68b0fd155ce3ba709 --check-only
```

The cloud workflow runs the same checks and targeted regression tests before
its computation jobs. Every result is retained, including failures and partial
outputs. Dispatching the workflow does not increase completed-case coverage.

Local validation passes **77 targeted tests**, including fixed-partition union,
rejection of omitted branches/imports/controls and changed tolerances, plus the
existing diagnostic, array-audit, control-inventory and complete-case tests.
