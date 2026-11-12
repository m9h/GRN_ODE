# Higher-precision trajectory diagnostics

The Marhl paired-learning branches disagree late in the full 0–300 interval
after tolerance refinement in RoadRunner, COPASI and SciPy Radau. These are
completed trajectories whose accuracy remains unresolved. The optional
[Taylor adapter](grn_memory/taylor_reference.py) tests whether increasing both
arithmetic precision and integration accuracy stabilizes that trajectory.

[Heyoka](https://bluescarni.github.io/heyoka.py/notebooks/arbitrary_precision.html)
provides an independent Taylor integrator with MPFR-backed arbitrary-precision
arithmetic. The [diagnostic](scripts/diagnose_taylor_paired.py) compares 128-bit
arithmetic with a `1e-30` truncation tolerance against 192-bit arithmetic with
`1e-45`, then compares both with RoadRunner at `1e-13/1e-15`. It preserves all
30,001 original observations, reset schedules, calibrated levels and the
`1e-7 + 2e-5*max(abs(a),abs(b))` acceptance rule. A separate untreated 0–50
baseline checks the model translation before interpreting the stimulated runs.

## Completed Marhl diagnostic

The [complete report](results/catalog-paired-taylor-marhl/report.json) covers
all three originally failed branches. All 12 integrations finish: three for
the untreated baseline and nine for the full stimulated trajectories. Each
stimulated integration preserves 998 resets, 999 segments, five observables
and all 30,001 samples. The untreated baseline agrees across all three runs.

| Original branch prefix | 128-bit vs 192-bit maximum scaled error | 192-bit vs RoadRunner maximum scaled error |
|---|---:|---:|
| `7b2974bb7882` | 0 | 192.54 |
| `d0e2345138b3` | 3.11e-11 | 43,530.71 |
| `d4e0182a177e` | 1.04e-11 | 37,731.53 |

A scaled error at most one passes the unchanged acceptance threshold. The
zero in the first row means the saved binary64 observations are identical;
it is not a claim of exact equality of arbitrary-precision internal states.
All three branches converge with precision but disagree with RoadRunner.
These results do not recover either original failed case, establish a unique
reference trajectory, or demonstrate chaotic dynamics.

The [array audit](results/catalog-paired-taylor-marhl/audit.json) verifies the
source hashes, original failure inventory, every sample and reset count, and
recomputes each comparison from the saved arrays. It needs only the main
project's Python environment:

```bash
uv run --locked python scripts/audit_taylor_paired.py \
  --input results/catalog-paired-taylor-marhl \
  --output results/catalog-paired-taylor-marhl/audit.json
```

Precision convergence and native agreement are reported separately. A stable
high-precision trajectory that disagrees with a native simulator is recorded
as `precision_converged_native_mismatch`, not a recovered case. This remains a
branch diagnostic; recovering either original Marhl case requires all its
controls and an independently validated full case calculation.

## Numeric and SBML semantics

All coefficients and initial values obtained from libSBML, and all recorded
reset inputs, are promoted from their binary64 values exactly. This isolates
integration arithmetic from changes to the supplied numeric inputs; it does
not recover extra significant digits in experimental parameters. Internal
state and dense output retain the requested precision through every segment
and reset. Only saved observations are rounded to binary64 for comparison
with the original simulators. Their full arrays and checksums are retained.

The adapter independently translates reaction arithmetic from the SBML syntax
tree, including fractional stoichiometry, local parameter scope and
amount/concentration conversion. Its state coordinates are concentrations.
It rejects native events, rules, initial assignments, function definitions,
conversion factors, dynamic or zero-dimensional compartments and unsupported
kinetic expressions. It is not a general SBML implementation. Eight analytic
tests check complete-state reset handling, units, fractional stoichiometry,
boundary species, unsupported semantics and ambiguous or conflicting resets.
Eight additional audit tests reject incomplete evidence, altered arrays,
missing resets and false agreement claims. The main environment passes 146
tests with the optional Heyoka module skipped; the separate Heyoka environment
passes all eight analytic adapter tests.

## Separate environment

The main replication project continues to use its existing uv environment.
Do not modify that environment while its workers are running.
GitHub computation jobs also use `uv sync` and `uv run`. Micromamba is only
the macOS native-library bootstrap described below; uv installs the additional
Python packages into that isolated environment.

On Linux x86-64, Heyoka supplies a binary wheel and uv can install the whole
diagnostic environment:

```bash
uv venv .venv-taylor --python 3.12
uv pip install --python .venv-taylor/bin/python heyoka==7.13.2 \
  -r environments/heyoka-python-requirements.txt
```

On macOS arm64, Heyoka's PyPI distribution requires a source build and native
C++ libraries. The [official installation guide](https://bluescarni.github.io/heyoka.py/install.html#packages)
also provides conda-forge binaries. The checked-in explicit environment fixes
all 54 native package builds and their recorded checksums; Python additions
are installed with uv afterward:

```bash
MAMBA_ROOT_PREFIX=/tmp/grn-taylor-mamba micromamba create --no-rc --yes \
  --prefix "$PWD/.venv-taylor" --file environments/heyoka-osx-arm64.explicit
uv pip install --python .venv-taylor/bin/python \
  -r environments/heyoka-python-requirements.txt
```

Run the analytic checks and the full diagnostic from `python/`:

```bash
HEYOKA_CACHE_DIR=/tmp/grn-taylor-cache OMP_NUM_THREADS=1 \
  .venv-taylor/bin/python -m pytest -q tests/test_taylor_reference.py
HEYOKA_CACHE_DIR=/tmp/grn-taylor-cache OMP_NUM_THREADS=1 MPLBACKEND=Agg \
  .venv-taylor/bin/python scripts/diagnose_taylor_paired.py --model 39 \
  --output results/catalog-paired-taylor-marhl
```

The report records Python, library and platform versions, source and model
hashes, the complete observation-grid hash, every reset count and integration
outcome. `--resume` reuses terminal records only when their complete metadata
fingerprint matches. Saved records and arrays should be kept together.

## Independent Marhl implementation

The model-specific [mpmath adapter](grn_memory/marhl_mpmath.py) transcribes the
seven reaction fluxes independently, including the one-quarter stoichiometries
for ER and mitochondrial calcium. It accepts only the original BioModel 39
checksum. This is a check of one model, not a general SBML importer.
Between interventions, its derivatives conserve `Ca_cyt + 4*CaER + 4*CaM + CaPr`
and `CaPr + Pr`; resetting a species can change the first conserved quantity.
Tests compare its rates with RoadRunner across widely separated states and
verify that resets preserve absolute time and every other state.

The [full diagnostic](scripts/diagnose_marhl_mpmath.py) evaluates the untreated
baseline and all three original failed branches with mpmath at 128 and 192 bits.
It compares each full array with the saved Heyoka and RoadRunner trajectories,
retaining every observation and intervention. Both arbitrary-precision
implementations use Taylor methods. Agreement would support consistency across
implementations, but would not establish agreement across integrator families
or validate the two complete cases without their remaining control arms.

```bash
.venv-taylor/bin/python -m pytest -q tests/test_marhl_mpmath.py
.venv-taylor/bin/python scripts/diagnose_marhl_mpmath.py \
  --output results/catalog-paired-mpmath-marhl
```

The mpmath diagnostic uses no Heyoka native libraries while integrating; its
equations and arithmetic can also run in a uv-created Python environment with
the pinned Python requirements above. No completed stimulated-branch result
is claimed here until the saved arrays have been independently audited.

The [separate array auditor](scripts/audit_marhl_mpmath.py) first re-audits the
published Heyoka/RoadRunner reference, then verifies every mpmath observation,
source hash, precision request and reset count. It recomputes all seven
comparisons for the baseline and each original failed branch. Twelve tests
use explicitly synthetic temporary records to reject truncated or changed
arrays, incomplete inventories, missed resets, altered arithmetic settings,
false comparisons and unsupported case-recovery claims. Those test fixtures
are not experimental results.

```bash
uv run --locked python scripts/audit_marhl_mpmath.py \
  --input results/catalog-paired-mpmath-marhl \
  --output results/catalog-paired-mpmath-marhl/audit.json
```

The audit requires a completed diagnostic and does not need mpmath or Heyoka
installed. The main environment passes 225 tests, with the optional Heyoka
adapter module skipped; the isolated precision environment separately passes
the nine mpmath adapter and resume tests.

## Complete control-arm computation

The two unresolved Marhl cases each require twelve arms. Their union contains
18 distinct branches: the three failed branches above and 15 other branches.
The [control runner](scripts/diagnose_marhl_controls.py) computes all 15 with
Heyoka and mpmath at both recorded precisions, plus RoadRunner at
`1e-13/1e-15`. It retains every original reset and all 30,001 observations for
each branch. Before starting, it validates the original case inventory and
re-audits the published Heyoka reference.

```bash
.venv-taylor/bin/python scripts/diagnose_marhl_controls.py \
  --output results/catalog-paired-marhl-controls
```

The runner saves the case-to-branch mapping, source and model checksums,
arithmetic settings, library versions, full trajectory arrays and reset counts.
It compares all six pairs of high-precision trajectories and reports their
agreement separately from the four comparisons with RoadRunner. `--resume`
requires unchanged configuration and verifies each completed array before
reusing it. Five tests reject missing case arms, incomplete resets, a changed
absolute clock and truncated cached arrays.
A sixth checks version recording for conda's Heyoka build, which exposes its
version without Python wheel metadata. The isolated precision environment
passes these six tests together with all nine mpmath adapter and resume tests.

These computations do not themselves recover either case. A combined audit
must validate all 18 branches and recompute the complete case scores from
consistent implementations across every arm before coverage can increase.

The [complete-case auditor](scripts/audit_marhl_cases.py) performs that check
after both computations finish. It re-audits the three failed-branch diagnostics,
requires all 15 control branches, and verifies compatible implementations,
arithmetic settings and producer environments across every arm. It recomputes
all ten pairwise trajectory comparisons for each branch and every window mean
from the saved arrays. Both 192-bit implementations must then agree on all
controlled case classifications. A failed baseline, unresolved precision check
or differing controlled classification prevents case promotion.

```bash
uv run --locked python scripts/audit_marhl_cases.py \
  --controls results/catalog-paired-marhl-controls \
  --mpmath results/catalog-paired-mpmath-marhl \
  --output results/catalog-paired-marhl-case-recovery/report.json
```

Native disagreement remains explicit, and original passing cases are reported
separately from any recovered cases. Thirteen tests exercise incomplete arms,
changed arrays or environments, failed controls, and a classification boundary
where pointwise-agreeing values nevertheless yield different controlled labels.
Their temporary fixtures deliberately contain invented trajectories and are
not simulation evidence. The auditor's availability does not change current
case coverage while the required computations are running.
