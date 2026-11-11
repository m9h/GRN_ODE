# Memory protocols across the 35-model catalog

**9 November 2026: all 538 stimulation cases across all 35 models pass independent
trajectory comparisons and the checks on resolved classifications. All 47 tests
pass with the optional JAX and delay dependencies installed.**
The [Linux reproduction](https://github.com/m9h/GRN_ODE/actions/runs/42707874609)
also passes all 538 cases, the baseline catalog, and the existing memory/JAX suites.

This extends the [baseline kinetics validation](CATALOG_VALIDATION.md) with a
single-input retention screen. Every independently writable state is stimulated
both up and down, and every other independent state is observed as a possible
response: **269 input states, 538 stimulation cases across all 35 models**.
Association, delayed cue recall, repeated stimulation and breaking acquired
responses remain subsequent catalog-wide stages. This screen alone does not
reproduce the original study's eight-category memory prevalence.

Numerical agreement does not certify that an intervention remains inside a
model's biological domain. For example, `M__up` and `X__up` in Goldbeter's
reduced oscillator set active fractions above 1. Those two cases remain in the
538-case mathematical screen, but require the [domain qualification](CATALOG_BREAKING.md#a-domain-limit-exposed-by-the-goldbeter-model)
before biological interpretation. The published numerical results are unchanged.

The 538 trajectories yield **4,680 input/direction/response assessments**.
Of these, **1,051** meet the matched-retention criterion and **1,721** have an
unresolved training effect at the declared numerical resolution. There are
**26 degenerate zero-baseline input cases**. The raw paper-like labels disagree
between engines for 76 response assessments, all unresolved; those labels are
retained in the report and excluded from validated memory interpretations.
The largest normalized trajectory discrepancy is approximately **0.574**;
the acceptance limit is one. These counts describe this screen, not independent
biological samples or a replication of the paper's population frequencies.

The source is the protocol in `MEMORY_EVALUATOR_ODE_SLURM1.m`,
`Get_R_US_NS_Exhaustive.m`, `stimulateRelaxSingle.m` and `DetectMem.m`, together
with [Biswas, Clawson and Levin](https://pmc.ncbi.nlm.nih.gov/articles/PMC9820177/).
The model-specific MATLAB functions are missing from the historical checkout.
We use verified SBML symbol identities and native model semantics rather than
assuming that an index in a saved MATLAB vector identifies a current SBML state.

## Protocol and complete state

Each experiment starts at the model's encoded initial conditions and runs
continuously from native time 0 to 650. The windows are:

| Window | Time | Intervention |
|---|---:|---|
| Calibration | 0–50 | None; measure each input's minimum and maximum |
| Training | 50–100 | Reset one input every 0.1 units, from 50.1 through 99.9 |
| Relaxation | 100–150 | No further resets |
| Extended relaxation | 150–650 | No further resets; report the final 50-unit mean |

Upward stimulation sets the input to 100 times its calibration maximum;
downward stimulation uses its minimum divided by 100. These are external
additions/removals, not changes to kinetic parameters. The first integration
block is unforced and the last block ends without another reset, matching
`stimulateRelaxSingle.m`. Calibration does not establish that every model has
reached a steady state. Native events and time-dependent drives remain active.

The [native protocol engine](grn_memory/native_protocols.py) writes temporary
SBML events and runs the entire history in each simulator. One event per input
train uses an integer counter to schedule its successive resets. Event-based
runs must execute the expected count. Original XML files remain unchanged. This
preserves rate-rule states, native time and native events across stimulation;
restarting a concentration-only state would not do so.

Assignment-rule quantities, constant species and fixed boundary species remain
observables but cannot be independent inputs. Rate-rule species and rate-rule
parameters can be inputs. Species inputs are specified in concentration units,
including conversion when their SBML symbols denote amounts. Every original
species and additional rule/event target is compared between simulators, not
only the states used in memory classifications.

For the Scheper clock, the [delay protocol engine](grn_memory/delay_protocols.py)
retains the complete past across jumps. A method-of-steps implementation splits
integration at resets and their propagated delay discontinuities. JiTCDDE supplies
an independent calculation, with explicit narrow history jumps and step/width
refinement. The prehistory remains `M=P=1` for times before zero. Resetting the
past to the current concentration would define a different experiment.

## Numerical agreement and unresolved labels

There are 65,001 sample times per trajectory. An otherwise uniform 0.01-unit
grid moves samples coinciding with resets to **reset time plus 0.000001**.
These are the actual recorded times; they are not relabeled as the discontinuity
instant. Both simulators and the untreated control use the same grid. This
avoids ambiguous left/right values and sensitivity to event-root rounding during
very fast post-reset transients. It is a documented sampling difference from
the historical MATLAB arrays.

Full-trajectory agreement requires, for each observable at every sample:

```text
abs(a - b) <= 1e-7 + 2e-5 * max(abs(a), abs(b))
```

This acceptance tolerance is unchanged across models. Integration tolerances
are `rtol=1e-12`, `atol=1e-14`, except Marhl2000 (network 30:
`1e-13`, `1e-15`). Late oscillatory phase in Marhl requires tighter integration.
For Rohwer2000 (network 35), RoadRunner retains `1e-12`, `1e-14`, while COPASI
uses `1e-8`, `1e-10`. COPASI's LSODA integration hit step limits at tighter
requests during several stiff reset transients. The recorded settings complete
all 26 input cases and agree with the tighter RoadRunner calculation under the
same full-trajectory acceptance threshold. Both still use the native SBML events.
The delay engine also compares steps 0.001 and 0.0005, with jump widths `1e-9`
and `5e-10` respectively. These checks concern numerical agreement, not biological
measurement error.

The report retains two descriptions of a response:

- **Paper-like retention:** a twofold training response relative to both the
  calibration mean and the time-matched untreated mean, followed by retention
  of at least half the shift from calibration. Raw labels and fractions remain
  visible even when their numerical interpretation is uncertain.
- **Matched retention:** compare the training and relaxed means to their own
  time-matched untreated means. Require at least half the training effect to
  remain after release. This distinguishes persistence of a treatment effect
  from natural drift or an oscillatory baseline.

Writing the matched effects as
$S_* = S-C_{train}$ and $L_* = L-C_{relax}$, the retained fraction is
$L_*/S_*$ when the training effect is resolved. Persistence can arise from
added material, a switch between attractors or an enduring phase shift. This
screen alone does not establish associative learning or a particular mechanism
of biological memory; those require the later protocol-specific controls.

A training effect smaller than twice the declared mixed comparison tolerance
at the training means is marked **unresolved**. Its matched-memory label is
`null`, not false. This is an operational resolution rule, not a statistical
confidence interval. Raw fold labels can disagree when two agreeing trajectories
have opposite tiny numerical tails near zero; those labels do not constitute
memory evidence. Any classification disagreement involving a resolved effect
still fails validation.

The Cao toggle-switch encoding has an all-zero initial state, also present in
the saved MATLAB initial vector. Multiplying its baseline by 100 cannot create
a stimulus. Such cases are computed and marked `degenerate_zero_baseline`;
they cannot establish that the network lacks memory under other initial states
or interventions. Tiny negative calibration minima are rounded to zero only
within 100 integration absolute tolerances, with the raw minimum retained.

## Reproduce and inspect

From `python/`, using Python 3.12 and a C compiler for JiTCDDE:

```sh
uv sync --locked --extra test --extra delay
uv run --locked --extra test --extra delay python -m pytest -q
uv run --locked --extra delay python -m grn_memory.catalog_memory --workers 3
```

Use `--network 14` for a single model, `--traces` to retain compressed trajectories,
and `--resume` to reuse passing cases only when the model, code, dependencies and
configuration fingerprints match. `--limit-inputs` is a debugging option;
limited runs are explicitly incomplete. Failed or partial native trajectories
are rejected. Each model runs in a separate process with a timeout and log.

The [machine-readable report](results/catalog-memory/report.json) and
[individual model reports](results/catalog-memory/) include all tested inputs,
clamp levels, excluded species, compared observables, worst errors, controls,
response means, unresolved labels and source hashes. Trajectories are regenerated
on demand. The integration and classification checks include exact solutions
with native events and rate rules, concentration/amount conversion, a delayed
jump with known history, and a zero-tail counterexample to raw fold labels.

## Remaining catalog-wide work

1. Use the single-input screen to identify regulating inputs and candidate
   neutral cues, then run paired, unpaired, sham-probe and delayed-probe controls.
2. Extend repeated stimulation and breaking/rechallenge experiments with the
   same complete-state and history semantics.
3. Extend JAX model and intervention coverage against these independent results.
4. Report final protocol coverage and deviations before comparing population
   frequencies with the historical results. Random-network experiments remain
   a separate expansion.
