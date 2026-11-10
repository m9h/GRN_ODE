# Intervening on acquired response histories

This stage extends the original MATLAB breaking-intervention search across the
35-model catalog. The selected-case [final pilot](results/catalog-breaking-pilot-final/report.json)
passes **119 branches across 24 conditional trials**, covering three initial
cases in networks 3, 26 and 35. Its largest normalized discrepancy is 0.58169
(acceptance limit 1), with one explicitly recorded solver retry. All 74 local
tests pass. The full-catalog search is running; **full-catalog breaking results
are not yet available.** The [validated repeated-stimulation screen](CATALOG_REPEATED.md)
provides the initial histories, stimulus levels and candidate responses.

The initial inventory contains **7,324 ordered UCS/breaker combinations and
37,086 response assessments**. Later trial counts depend on earlier results.
Networks 6, 14, 17 and 33 have no eligible initial combinations under the
specified rule; they still receive independently compared untreated controls.
Zero eligible combinations do not establish an absence of learning capacity.

## Source protocol and documented discrepancies

The operational source is
[`Find_DrugRes_Sensitize_SLURM1.m`](../Find_DrugRes_Sensitize_SLURM1.m), using
[`stimulateRelaxSingle.m`](../stimulateRelaxSingle.m) for the later exposures.
The search has up to three trials: a first new input B, the same input B again
if required, then every eligible different input C if still required. Each
trial contains one breaker exposure, a rest, one UCS rechallenge and a rest.

The [paper's sections 2.7–2.8 and 4.5–4.6](https://pmc.ncbi.nlm.nih.gov/articles/PMC9820177/)
describe sequences and scoring that differ from the checkout: some descriptions
use two breaker exposures or two UCS tests per trial. We follow the code's
explicit sequence and record its rule alongside additional controls. We do not
claim to reproduce a uniquely specified historical protocol or its prevalence.

One additional code defect is corrected: after computing `X9`, the resistance
branch sets `GenesDrugResis7 = X8(end,:)` before computing `X10`, discarding the
second rechallenge's state change. Our continuous simulation retains the actual
evolved state through every exposure and relaxation. This also preserves native
time, event state, rule variables and delay history. The original XML is unchanged.

## Eligibility and complete search

Initial eligibility is the **union** of the two engines' raw MATLAB resistance
and sensitization labels in the validated repeated screen. This covers either
engine's search path despite the numerical fragility of some raw labels. Every
candidate retains both engines' eligibility, phenotype and last nonzero pulse
code; the controlled repeated-pulse categories remain available in the source
report.

For each eligible UCS/response pair, B ranges over every other independently
writable state, in both directions with nonzero calibrated reset levels. C must
also differ from B. Thus the first trial requires three distinct identities,
and the third requires four. As in the MATLAB search, zero breaker levels are
excluded rather than replaced by invented nonzero doses. All levels come from
the original repeated screen's untreated 0–1010 calibration, even though the
new experiment can last longer.

For each response, a trial continues if either engine that considered the
response eligible has not passed the raw MATLAB reversal test. A raw-positive
result can stop a path while failing controlled interpretation. Both facts are
reported; the controls do not silently change the source algorithm's search
order. If the third trial is reached, every eligible C/direction is tested.
Responses with no available fourth identity are recorded explicitly.

## Continuous timeline

The six original pulses and intervening rests occupy 0–1010. Each later phase
lasts 100 native time units:

| Trial | Breaker | Rest before test | UCS rechallenge | Rest after test |
|---|---|---|---|---|
| 1 | B: 1010–1110 | 1110–1210 | 1210–1310 | 1310–1410 |
| 2, if required | B: 1410–1510 | 1510–1610 | 1610–1710 | 1710–1810 |
| 3, if required | C: 1810–1910 | 1910–2010 | 2010–2110 | 2110–2210 |

Later exposures use 999 resets at interval 0.1, excluding onset and withdrawal,
matching the single-stimulus helper. The six-pulse prefix keeps its 4,506 resets,
including onset and withdrawal. A full three-trial treated branch therefore
has **10,500 resets**. All branches run from the original model initial state;
no concentration-only restart approximates an evolved state.

## Eight controls at each trial

Three binary factors produce eight arms:

1. The original six-pulse history is present or absent.
2. The breaker sequence through the current trial is present or sham.
3. The current UCS rechallenge is present or sham.

**Earlier UCS rechallenges remain in every corresponding arm**, including the
current-cue sham. At trials 2 and 3, the group without initial training has
therefore still received earlier test pulses. This matches prior probe history
and prevents the last probe's effect from being confused with prior tests.
Identical complete intervention schedules, integration settings and end times
share a simulation branch.

Let $Y_{h,b,q}$ be the mean response during the current rechallenge window:
$h$ indicates the original six-pulse history, $b$ the breaker sequence and $q$
the current UCS cue. The incremental cue effect is

$$G_{h,b}=Y_{h,b,1}-Y_{h,b,0}.$$

The history-dependent cue effect without and with the breaker is

$$E_0=G_{1,0}-G_{0,0},\qquad E_B=G_{1,1}-G_{0,1}.$$

Their difference $E_B-E_0$ tests whether the breaker changes the effect of the
initial history. Persistent level shifts and direct cue effects shared by both
initial-history groups cancel. If $E_0$ is unresolved, the case cannot establish
breaking of an acquired cue response at this clock time: it may have already
decayed, or the raw pretest may have measured something else.

The operational restoration criterion is a resolved reduction by at least half:

$$\tfrac12|E_0|-|E_B|>\epsilon,$$

where $\epsilon=\tfrac12\epsilon_{E_0}+\epsilon_{E_B}$. Each linear contrast's
resolution is the sum of the absolute-coefficient-weighted per-mean tolerances
$10^{-7}+2\times10^{-5}|Y|$. This is an operational numerical-resolution rule,
not a confidence interval or a rigorous integration-error bound.

Categories distinguish half restoration, reversal, amplification, a smaller
change, no resolved breaker effect, no remaining resolved history effect, a
threshold ambiguity, and negative response states. Both engines must agree on
the category and all component contrast directions. A reduction is a finite
model response, not evidence of a particular mechanism or clinical efficacy.

The raw MATLAB score is also retained: a mean at least 1.5 times the preceding
rest receives an upward reversal label if the source's last code was downward;
a mean at most the preceding rest divided by 1.5 receives the converse label.
This includes the original zero-equality artifact. Raw differences are audited
separately from the controlled validation gate.

## Validation, checkpoints and evidence

The default output grid is 0.01 native time units. Samples coinciding with any
possible reset move to the actual time reset +$10^{-5}$, in every arm. Means are
arithmetic sample means, not converged continuous-time integrals. Every original
observable at every sampled time must meet the unchanged comparison threshold
$10^{-7}+2\times10^{-5}\max(|a|,|b|)$.

Integration requests and case-specific overrides come from the repeated screen.
For Rohwer, COPASI has one declared fallback, `rtol=1e-7`, `atol=1e-9`, only if
the original request raises a solver error or returns a partial trajectory.
Every attempt and the settings actually used are recorded. A completed trajectory
that fails the independent comparison is not retried under looser settings.
The need arose in a third-trial control after repeated `EIIAP` stimulation:
the ordinary request stopped at about 2030.41; the fallback completed all
221,001 samples with a normalized discrepancy of 0.15533. A still looser
`1e-6/1e-8` diagnostic failed comparison and is not an allowed fallback.
The Yoon timed-drive event representation receives an additional untreated
comparison with the original encoding in each engine over the full 0–2210
window. Delay controls receive the independent step/jump-width refinement.
Negative response ranges beyond tolerance are retained and marked as outside
the physical interpretation of concentration-based learning.

```bash
uv sync --locked --extra test --extra delay
MPLBACKEND=Agg uv run --locked --extra test --extra delay python -m pytest -q tests/test_catalog_breaking.py tests/test_protocol_retries.py
MPLBACKEND=Agg uv run --locked --extra delay python -m grn_memory.catalog_breaking --workers 3 --timeout 86400 --output results/catalog-breaking
```

Use `--resume` after interruption. Fingerprints cover the complete configuration,
source code, model XML, repeated-screen reference file, candidate plan and package
versions. Passed branch and case checkpoints are reused only when these match.
Failed branches are retried on resume. A bounded in-memory cache avoids retaining
the full search tree in RAM. `--timeout` is per model; it does not alter the
experiment. Partial `--limit-cases` or `--case` selections do not pass coverage.

Each model's JSON records case coverage and a manifest of hashed compressed
evidence shards. Branch shards contain schedules, integration settings,
cross-engine comparisons and every original observable's window means and ranges.
Case shards contain each conditional trial, response scores, search continuation
and branch references. They use gzip JSON Lines, with at most 100 records per
shard; Python's `gzip` module or `gzip -dc` can read them. Local atomic checkpoints
live in the ignored `.evidence/` directory. Published manifests identify exactly
which records belong to that run, excluding unused old checkpoints.

Ten tests cover residual levels, shared direct effects, restoration versus
overshoot, unresolved and negative states, raw continuation across engines,
the full three-trial schedule, distinct node identities, checkpoint provenance
and the exhaustive candidate inventory, plus bounded solver retries that cannot
turn a completed numerical mismatch into a pass. All ten pass locally. The
selected-case pilot is deliberately partial, so its aggregate status remains
incomplete despite all selected cases passing. Full run findings will be
recorded when their evidence is complete.
