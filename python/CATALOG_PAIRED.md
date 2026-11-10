# Paired exposure, transfer and delayed cue tests across the catalog

This stage extends the five-model demonstrations to every eligible ordered
UCS/CS/response combination in the original 35-model catalog. The implementation
and control tests are in place. Twelve pilot cases across networks 1, 4, 13,
26, 30 and 35 pass, as does network 14's untreated delay control: **133 distinct
branches pass**, with a largest normalized trajectory discrepancy of 0.05873
(acceptance limit 1). Controlled classifications agree; four response assessments
have raw paper-style label differences, retained for inspection. The full run
is in progress. **Full catalog results are not yet available.** The
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
and complete candidate counts. The full-catalog outcome will be reported when
available. Pilot case selection is deliberately partial, so its aggregate has
an incomplete-coverage status despite all selected cases passing.
