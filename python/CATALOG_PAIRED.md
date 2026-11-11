# Paired exposure, transfer and delayed cue tests across the catalog

This stage extends the five-model demonstrations to every eligible ordered
UCS/CS/response combination in the original 35-model catalog. The first full
screen has evaluated **all 4,208 cases and 22,578 distinct branches across all
35 models**. **4,166 cases pass; 42 do not.** All cases pass in 31 models.
The [aggregate report](results/catalog-paired/report.json) links the original
per-model results and hashed branch archives, including failures.

The [coverage and evidence audit](results/catalog-paired/audit.json) independently
rebuilds the candidate inventory, checks source/model/reference/archive hashes,
verifies every branch reference, and recomputes the scores from saved window
summaries. It establishes complete attempted coverage, not successful integration
for every branch. Of 22,578 branches, **22,481 pass, 77 have incomplete solver
output, and 20 complete but disagree beyond the full-horizon tolerance**.
Follow-up recoveries are separate evidence and have not been substituted into
this original report.

| Network | Model | Cases passing | Incomplete branches | Completed mismatches |
|---|---|---:|---:|---:|
| 25 | François two-gene network, BioModel 539 | 43/44 | 1 | 0 |
| 30 | Marhl calcium oscillations, BioModel 39 | 24/26 | 0 | 3 |
| 32 | Vilar circadian oscillator, BioModel 35 | 136/142 | 7 | 9 |
| 35 | Rohwer phosphotransferase system, BioModel 38 | 416/449 | 69 | 8 |

Earlier pilots remain useful reproducibility checks. Twelve pilot cases across networks 1, 4, 13,
26, 30 and 35 pass, as does network 14's untreated delay control: **133 distinct
branches pass**, with a largest normalized trajectory discrepancy of 0.05873
(acceptance limit 1). Controlled classifications agree; four response assessments
have raw paper-style label differences, retained for inspection. The
[pilot report](results/catalog-paired-pilot/report.json) links the selected-case
evidence. A second [smoke run](results/catalog-paired-pilot-smoke/report.json)
fully covers networks 16 and 19 (six cases), plus network 14's delay control;
all 61 branches pass. CI runs this small complete selection afresh.

The validated [single-input screen](CATALOG_MEMORY.md) supplies stimulation
levels and candidate identities. It yields **4,208 ordered stimulus pairs and
13,080 response assessments**, requiring **22,578 distinct continuous simulation
branches** after sharing identical histories. Each branch is checked with two
independent engines, at every sampled time and for every original observable.

Networks 3, 6, 14, 17 and 33 have no eligible triples under this selection rule.
They remain in the audit with an untreated control and an explicit zero-case
record. This does not establish that those models cannot learn under another
protocol. In particular, a protocol requiring three distinct independent state
variables cannot be applied to a model with only two such variables.

## Candidate selection and stimulation

For each response, a UCS must produce a resolved training effect and the same
nonzero twofold regulation label in both reference engines. A candidate CS must
have no resolved twofold response in either engine. Subthreshold and numerically
unresolved effects are eligible candidates; neither establishes absolute
neutrality. UCS, CS and response must be three distinct independently writable
states. All eligible UCS rows are retained.

Stimulation uses the single-input reference's unchanged levels: 100 times the
maximum or one hundredth of the minimum over the original untreated 0–50 window.
Zero levels remain zero. A 50-unit exposure has 499 concentration resets,
0.1 units apart, starting at exposure onset +0.1 and ending at offset −0.1.
The first block is unforced; no reset is applied at withdrawal. Species amounts
and rate-rule parameters retain the conventions in the single-input guide.

Every branch starts from the model's original initial state and runs continuously
through native time 300. Native events, rule variables and, where applicable,
delay history are retained. No evolved state is copied into a fresh simulator.
The source XML remains unchanged.

## Twelve arms per ordered stimulus pair

Four training histories are compared: no training, UCS alone, CS alone, and
UCS plus CS together. Each history has three independent subsequent branches:

| Native time | Sham | Ordinary cue | Delayed cue |
|---|---|---|---|
| 0–50 | Untreated baseline | Same | Same |
| 50–100 | Assigned training history | Same | Same |
| 100–150 | Washout | Washout | Washout |
| 150–200 | No intervention | CS probe | Further washout |
| 200–250 | No intervention | Post-probe recall | CS probe |
| 250–300 | No intervention | Continued relaxation | Post-probe recall |

The delayed branch receives no earlier probe. The naive controls receive the
same CS level, reset schedule and clock time as trained branches. CS-only
pre-exposure controls distinguish a contribution of paired training from a
history of exposure to the cue itself. UCS-only histories test transfer.

Identical schedules are simulated once per model. For example, reversing the
UCS and CS roles preserves the paired-training sham but changes which species
is probed, so those probe branches are distinct. Branch identifiers are hashes
of the complete training/probe specification, and every case links its twelve
roles to the corresponding archived records.

## What the measurements mean

Let $Y_{h,c}$ denote the arithmetic mean response during a cue window, where
$h\in\{0,U,C,UC\}$ is training history and $c\in\{0,1\}$ indicates whether a
cue is delivered. The cue's incremental effect at that clock time is

$$G_h=Y_{h,1}-Y_{h,0}.$$

Subtracting the same-history sham removes persistent training effects and
ongoing drift. We retain every $G_h$, the contrasts $G_{UC}-G_h$ for each simpler
history, and the factorial interaction

$$I=G_{UC}-G_U-G_C+G_0.$$

An operational **joint-exposure candidate** requires a resolved $G_{UC}$,
an interaction $I$ in the same direction, and a resolved difference from each
simpler history in that direction. Negative response values beyond the stated
numerical tolerance exclude this interpretation and are flagged separately.
Other categories distinguish an unresolved cue effect from a cue response that
does not meet joint-specificity criteria.

These are causal contrasts within the specified deterministic model. They are
not proof of associative learning, a biological mechanism, or dependence on the
simultaneity of the inputs. An explicitly unpaired training schedule would be
needed to test the last claim. Pool changes, nonlinear dynamics and other
ordinary mechanisms can produce nonadditivity.

For a linear contrast $L=\sum_i w_iY_i$, its numerical resolution threshold is

$$\epsilon_L=\sum_i |w_i|(10^{-7}+2\times10^{-5}|Y_i|).$$

Values within that threshold are unresolved. This is a conservative operational
rule based on the trajectory-comparison tolerance, not a statistical confidence
interval or a rigorous bound on integration error. Both engines must agree on
every controlled categorical result, including component contrast directions.

Recall uses the trained/probed response minus its trained/sham counterpart in
the following 50-unit window. It compares that incremental effect with half the
incremental effect during the cue. The categories are retained half, below half,
threshold unresolved, unresolved cue effect, and negative response state.

## Concordance with the MATLAB experiments

The reports also preserve the intended threshold-based categories from
`Get_R_US_NS_Exhaustive.m`, `Test_US_Memory.m`, `Test_Pairing_Memory.m`, `AL.m`,
`UCS_NS_Asso.m`, `DetectRegR.m` and `DetectMem.m`:

- Twofold UCS/CS pretests and UCS/pairing retention.
- The 1.5-fold association and UCS-only transfer tests.
- At least half-retention for long recall; otherwise short recall.
- A later-relaxation candidate corresponding to the MATLAB consolidation branch.
- A separate delayed-cue candidate with a matched sham, following the paper's
  verbal notion of delayed acquisition of a cue response.

Raw labels may overlap and are not converted into historical population
percentages. A `pairing_memory_without_ucs_memory` field exposes the original
priority of UCS memory. Raw label disagreements between engines are retained
separately from the controlled validation gate.

The [known MATLAB implementation problems](README.md#differences-and-limits)
remain corrected: failure is a Boolean rather than a nonzero `9999`, all UCS
rows are tested, and zero/zero is not regulation. The MATLAB later-relaxation
branch and the added delayed-cue test are explicitly different measurements.
The model-specific MATLAB functions are missing, so this is an SBML-based
reimplementation of the intended demonstrations, not a bitwise replication of
historical arrays or frequencies.

## Numerical checks and reproducibility

Output spacing is 0.01 native time units. Samples coincident with any possible
reset are evaluated at that time +$10^{-5}$ in **all** arms, including shams.
Window summaries are sample means and ranges, not converged continuous-time
integrals. Acceptance remains $10^{-7}+2\times10^{-5}\max(|a|,|b|)$ at every
sample of every original observable.

Integration requests follow the single-input reference. Network 26 uses the
same explicitly checked, equivalent timed-drive event representation developed
for the [repeated-input stage](CATALOG_REPEATED.md), at relative/absolute requests
$10^{-12}/10^{-18}$. Its untreated trajectory is additionally compared with the
original encoding in each engine. The original source hash and encoded hash
are recorded. Delay controls receive the independent JiTCDDE step and jump-width
refinement used by the other catalog protocols.

The full screen exposed a partial COPASI trajectory for François's two-gene
network (25, BioModel 539), in `A__up--gB__up` after UCS-only training followed
by the normal cue. Its request at `rtol=1e-12`, `atol=1e-14` stopped at 18,462
of 30,001 samples. Network 25 now permits one retry at `1e-11/1e-13` after a
solver exception. Both attempts and their settings are recorded. A completed
trajectory that disagrees with RoadRunner is not retried, and the acceptance
threshold above is unchanged. An [isolated rerun](results/catalog-paired-recovery/BIOMD0000000539.json) passes all 12 branches of this
case, including its shared untreated arm; this is selected-case evidence, not
full-catalog validation. The same selected case also passes the
[Linux solver-regression job](https://github.com/m9h/GRN_ODE/actions/runs/42766999555).
The original full report is retained at its recorded source revision.

A subsequent [complete François rerun](results/catalog-paired-francois-full-recovery/report.json)
passes **44/44 cases and 275/275 distinct branches**, with a largest normalized
trajectory discrepancy of **0.51135** (acceptance limit 1). Exactly one branch
uses the declared COPASI fallback: its initial attempt again stops at 18,462
samples, and the retry completes all 30,001 samples with normalized discrepancy
0.000688. The failed attempt remains in the branch archive. The
[recovery audit](results/catalog-paired-francois-full-recovery/audit.json)
rebuilds all 44 candidate plans, verifies source and evidence hashes, and
recomputes every score. This is complete coverage of network 25; the original
35-model report above remains unchanged, and the other three models' failures
remain unresolved.

To audit this complete model separately:

```bash
python scripts/audit_paired_catalog.py --network 25 \
  --input results/catalog-paired-francois-full-recovery \
  --source-revision 4108edeca8b2d6d5e454167454a8826319ff6046
```

### Independent JAX reset diagnostic

The optional [JAX protocol adapter](grn_memory/jax_protocols.py) carries every
independent state and absolute time between exact external resets. It supports
autonomous reaction models with fixed positive-volume compartments and derived
assignment-rule observables. Native events, delays, rate/algebraic rules,
initial assignments and conversion factors are explicitly unsupported here.
These restrictions do not change the native catalog's coverage. Eighteen adapter
tests include analytic solutions, amount/concentration conversion, simultaneous
resets, source-cache invalidation and comparisons with both native engines.

The [two-branch Rohwer diagnostic](results/catalog-paired-jax-rohwer/report.json)
preserves the original full 30,001-sample grid and comparison tolerance. Kvaerno5
at `1e-7/1e-9` completes branch `d4ace2879cde…` and agrees with RoadRunner
(maximum normalized discrepancy 0.11736). It reaches its step limit on
`698ea588e8ce…` during `[178.8, 178.9]`. Tenfold tighter JAX requests fail in
the initial untreated interval for both branches, while RoadRunner completes
both requests and agrees with its own refinement. Thus neither branch passes
the complete diagnostic's refinement gate; the single successful comparison
does not establish a general JAX recovery. Original COPASI failures remain
unchanged and visible.

An [alternative Kvaerno3 run](results/catalog-paired-jax-rohwer-kvaerno3/report.json)
confirms `d4ace2879cde…` at both requests: all five cross-engine and refinement
comparisons pass, with largest normalized discrepancy 0.09270. On
`698ea588e8ce…`, the `1e-7/1e-9` trajectory completes and agrees with RoadRunner
(0.07689), but the tighter JAX request stops during `[169.4, 169.5]`.
That branch remains unconfirmed under this diagnostic's refinement gate.
The adapter exposes Kvaerno3, Kvaerno4 and Kvaerno5 as explicit settings, with
analytic and two-engine reset checks for each. It does not retry failed
trajectories automatically. Add `--solver Kvaerno3` to reproduce this comparison
in a separate output directory.

The subsequent [complete 77-branch Kvaerno3 diagnostic](results/catalog-paired-jax-rohwer-full/report.json)
uses JAX requests `1e-6/1e-8` and `1e-7/1e-9`, together with RoadRunner
`1e-12/1e-14` and `1e-13/1e-15`. Its outcome is **23 confirmed, 42 with an
incomplete integration, and 12 completed mismatches**. The unchanged full-grid
comparison threshold applies even though these JAX integration requests are
looser than in the two-branch pilot. This establishes partial numerical recovery,
not recovery of Rohwer's 33 originally failed cases.

The [evidence audit](results/catalog-paired-jax-rohwer-full/audit.json) verifies
all 77 original failed branch identities, source hashes, complete comparison
inventories and outcome consistency. Reproduce the integrations from source
`40ca8ff586220a5df573e7d383defa2c19ed829a` with:

```bash
python scripts/diagnose_jax_paired.py --model 38 --solver Kvaerno3 \
  --rtol 1e-6 --atol 1e-8 --output results/catalog-paired-jax-rohwer-full
```

Audit the saved evidence from this checkout with:

```bash
python scripts/audit_jax_paired_diagnostic.py \
  --input results/catalog-paired-jax-rohwer-full \
  --source-revision 40ca8ff586220a5df573e7d383defa2c19ed829a
```

Implicit stages also expose `--root-finder Newton --root-find-max-steps 20` as
an explicit alternative to the default cached-chord method with ten iterations.
These options change how each implicit stage is solved; they do not change the
SBML equations, reset schedule or trajectory acceptance threshold. The compile
cache and evidence fingerprints include the chosen method and iteration limit.
The Newton configuration has its own analytic and native-engine reset check.
Complete failed-branch diagnostics remain separate from the original screen;
a branch confirmation does not establish agreement on every case-level score.

To check all 77 originally failed Rohwer branches with the Newton configuration:

```bash
python scripts/diagnose_jax_paired.py --model 38 \
  --root-finder Newton --root-find-max-steps 20 \
  --output results/catalog-paired-jax-rohwer-newton
```

This requests JAX tolerances `1e-7/1e-9` and `1e-8/1e-10`, plus the original
RoadRunner settings and their tenfold refinement. Every confirmation requires
all five full-trajectory comparisons. The difficult branch `698ea588e8ce…` is
also exercised by CI, with an explicit assertion on that gate.

```bash
python scripts/diagnose_jax_paired.py --model 38 \
  --branch d4ace2879cdea75e43b77bc82f97ecb73cab9ff6ba258b3e85f6838b0f44c593 \
  --branch 698ea588e8ce617393a9d712c09db85d171278dff6e9291ce785e1e3f71924df \
  --output results/catalog-paired-jax-rohwer
```

### Vilar: completed JAX audit and an independent stiff reference

The [complete Vilar failed-branch audit](results/catalog-paired-jax-vilar/report.json)
checks all 16 original failures using Kvaerno5 at `1e-10/1e-12` and
`1e-11/1e-13`, plus the original RoadRunner request and its tenfold refinement.
Every branch has an incomplete JAX integration, so none is confirmed. On nine
branches RoadRunner also disagrees with its own tighter request beyond the
acceptance threshold. Those original native results cannot serve as an
unquestioned reference. The audit used the source at `40ca8ff`; every failed
attempt, full-grid native comparison and completed window summary is retained.

The optional [SciPy reference adapter](grn_memory/scipy_reference.py) offers a
different stiff integrator. Jaxkineticmodel supplies the equations and JAX their
state Jacobian; SciPy supplies Radau or BDF integration between resets. This
shares the JAX importer's semantics, so comparison with native SBML integration
remains necessary. This wrapper does not expose gradients through integration.
Six tests check analytic decay, symbol units, retained unforced states,
assignment observables, both native engines, source-cache invalidation and
rejection of unsupported events or ambiguous observations.

The [SciPy diagnostic](scripts/diagnose_scipy_paired.py) uses two SciPy requests
and two tighter RoadRunner requests. Its five confirmation comparisons require
cross-engine agreement and stability within each engine. The original native
request is rerun separately, preserving its disagreement where it occurs.
No original case is promoted based on a single successful comparison, and the
conditional case scores still require their own recovery audit.

```bash
uv run --locked --extra test --extra jaxkineticmodel python -m pytest -q tests/test_scipy_reference.py
uv run --locked --extra test --extra jaxkineticmodel python scripts/diagnose_scipy_paired.py \
  --model 35 --output results/catalog-paired-scipy-vilar
```

The default requests are `1e-10/1e-12` and `1e-11/1e-13` for SciPy, and
`1e-13/1e-15` and `5e-14/5e-16` for RoadRunner. These are integration requests;
the unchanged comparison remains `1e-7 + 2e-5 * max(abs(a), abs(b))` at all
30,001 original observation times and for every original observable. Completed
interval counts and solver evaluations are persisted during the diagnostic.

### Recovering complete cases from Radau diagnostics

The [case recovery audit](scripts/recover_scipy_paired_cases.py) rebuilds the
original candidate inventory and all 12 arms of every originally failed case.
For Vilar, the six failed cases need **58 distinct branches**, including **42
controls in addition to the 16 originally failed branches**. Confirming those
16 branches alone cannot establish recovery of the six cases.

Every recovered case must use `scipy_refined` and `roadrunner_refined` throughout
all its arms. Every branch must pass all five full-trajectory comparisons,
with all 30,001 samples and original observables. The audit checks model, source,
calibration, schedule and evidence hashes, reset counts, window completeness,
and the consistency of pass flags with recorded errors. It then recomputes every
response's controlled classifications and requires agreement between the two
engines. Paper-style labels and any disagreements remain separate outputs.

The audit preserves the original passing cases, reports newly recovered cases
separately, and explicitly identifies missing or unconfirmed controls. It never
mixes engines within a case, combines different diagnostic configurations, or
turns a partial selection into a model pass. It checks saved pointwise comparison
results and recomputes scores from window summaries; it does not reconstruct or
rerun full trajectories. Use the recorded checkout and dependency environment.

Generate the complete recovery plan, then run all its branches (this can take
hours):

```bash
MPLBACKEND=Agg uv run --locked --extra test --extra jaxkineticmodel \
  python scripts/recover_scipy_paired_cases.py --model 35 \
  --output results/vilar-case-recovery/plan.json

MPLBACKEND=Agg uv run --locked --extra test --extra jaxkineticmodel python - <<'PY'
import json
from pathlib import Path
import subprocess
import sys
plan = json.loads(Path("results/vilar-case-recovery/plan.json").read_text())
command = [sys.executable, "scripts/diagnose_scipy_paired.py", "--model", "35",
           "--resume", "--output", "results/vilar-case-branches"]
for branch in plan["required_branch_ids"]:
    command.extend(["--branch", branch])
subprocess.run(command, check=True)
PY

MPLBACKEND=Agg uv run --locked --extra test --extra jaxkineticmodel \
  python scripts/recover_scipy_paired_cases.py --model 35 \
  --diagnostics results/vilar-case-branches \
  --output results/vilar-case-recovery/report.json
```

Multiple disjoint diagnostic directories can be supplied by repeating
`--diagnostics`; `unselected_branch_ids` lists the additional branches needed
beyond their declared selections. A successful audit exit establishes evidence
consistency, not numerical recovery: inspect `all_cases_validated`,
`recovered_cases`, and each case's status. The Vilar recovery runs are ongoing.
The full original screen and its original failures remain unchanged.

### Reset-encoding diagnostic for Vilar and Rohwer

The [explicit-reset diagnostic](scripts/diagnose_explicit_resets.py) replaces
each compact self-rescheduling event with individually timed events, preserving
every scheduled assignment and checking every final reset count. On three
selected failed branches, the explicit and compact RoadRunner trajectories agree
at all 30,001 sampled times (largest normalized discrepancy 0.00817).
COPASI still returns incomplete output on the selected
[Vilar branch](results/catalog-paired-explicit-diagnostic/35-223eba38bdcf.json)
and [first Rohwer branch](results/catalog-paired-explicit-diagnostic/38-698ea588e8ce.json).
The [second Rohwer branch](results/catalog-paired-explicit-diagnostic/38-d4ace2879cde.json)
completes but fails comparison, with normalized discrepancy 11.45248.
This alternative representation therefore does not resolve those failures and
is not used by the production screen. Original results and acceptance thresholds
remain unchanged.

For example, reproduce the Vilar diagnostic with:

```bash
MPLBACKEND=Agg uv run --locked python scripts/diagnose_explicit_resets.py \
  --model 35 \
  --branch 223eba38bdcf2bb1ec64ac048b179d978cf09281f6fa0f0afd0501d2ae4705a3 \
  --output results/catalog-paired-explicit-diagnostic/35-223eba38bdcf.json
```

### Late divergence in the Marhl calcium model

The first full screen also found **three completed, disagreeing branches in two
Marhl cases** (network 30, BioModel 39). They involve `CaER__down` cues following
`CaM__up` or `Ca_cyt__up` training. These are not partial-output failures and
are not eligible for the solver retry above.

The [reproducible diagnostic](scripts/diagnose_marhl_paired.py) compares both
engines at three integration requests: `1e-12/1e-14`, `1e-13/1e-15`, and
`3e-14/3e-16`. All nine comparisons pass through time **250**, the end of normal
recall; none passes across the entire **0–300** horizon. At the default request,
the first disagreement beyond tolerance appears after time 269. Refining each
engine also changes its late trajectory. These observations establish a late
numerical convergence problem, not a diagnosis of chaos.

The [diagnostic report](results/catalog-paired-marhl-diagnostic/report.json)
records the full-horizon failures, window comparisons, refinement comparisons,
source hashes and settings. Its
[plot](results/catalog-paired-marhl-diagnostic/late-divergence.png) shows the
timing of the divergence. Normal-cue and normal-recall scores do not use the
250–300 tail of these normal-probe branches; delayed-probe scores use separate
branches. The original two cases nevertheless remain **mismatches under the
full-horizon validation gate**. Agreement of their controlled categories does
not validate the divergent tail, and the protocol has not been shortened to
obtain a pass.

```bash
MPLBACKEND=Agg uv run --locked python scripts/diagnose_marhl_paired.py
```

```bash
uv sync --locked --extra test --extra delay
MPLBACKEND=Agg uv run --locked --extra test --extra delay python -m pytest -q tests/test_catalog_paired.py
MPLBACKEND=Agg uv run --locked --extra delay python -m grn_memory.catalog_paired --workers 3 --output results/catalog-paired
```

Add `--resume` after interruption. Source, model, reference-file, configuration,
candidate-plan and package-version fingerprints must match before a branch can
be reused. The default worker timeout is four hours per model; `--timeout`
changes the execution budget without changing the experiment. `--network`,
`--limit-cases` and `--case` support diagnosis. A partial case selection does
not pass the full-coverage gate.

The per-model JSON contains case scores and branch references. A hashed
`*-branches.jsonl.gz` archive contains each complete branch's schedule,
cross-engine comparison, and window means/minima/maxima. Decompress it with
Python's `gzip` module or `gzip -dc` to inspect one JSON record per line. The
ignored `.branches/` directory provides atomic per-branch checkpoints; the
published archive contains the resulting evidence. Full trajectories are
compared in memory and are not stored by this command.

Nine focused tests cover persistent stimulation, clock-dependent cue effects,
UCS-only and CS-only explanations, additive versus nonadditive exposure,
unresolved and negative states, the Boolean-recall bug, the distinction between
relaxation and delayed probing, independent recall windows, schedule identity
and complete candidate counts. Pilot case selection is deliberately partial, so its aggregate has
an incomplete-coverage status despite all selected cases passing.

Audit the published full-screen evidence without running new integrations:

```bash
MPLBACKEND=Agg uv run --locked python scripts/audit_paired_catalog.py \
  --source-revision 70a3afad61357e94873ff62a7300c099b4c7ae3e
```

The audit's successful exit means the evidence is internally consistent and
the full candidate inventory was attempted. Its output explicitly retains
`all_numerical_validations_passed: false`. Trajectories are not stored, so this
audit recomputes classifications from recorded window summaries, rather than
rerunning the full pointwise simulator comparison.
