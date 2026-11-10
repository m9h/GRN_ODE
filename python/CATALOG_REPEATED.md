# Repeated stimulation across the BioModels catalog

This stage extends the single-input [retention screen](CATALOG_MEMORY.md) to
six repeated pulses, following `Find_DrugRes_Sensitize_SLURM1.m` and `multiDrug.m`.
The clean full-catalog verification passes **all 538 input cases across all 35
models**. Every controlled pulse classification agrees between engines. The
[aggregate report](results/catalog-repeated/report.json) links the complete
per-model evidence. An initial 535/538 attempt identified three numerical
failures; the documented adjustments below resolved them without changing the
trajectory acceptance tolerance.

Every independently writable state is tested up and down. For each case, the
continuous six-pulse history is compared with five additional histories that
receive only pulse 2, 3, 4, 5 or 6, respectively. Each isolated pulse occurs at
the same absolute time and has the same duration as its repeated counterpart.
The first pulse already has identical prior history in both arms, so its
trajectory is reused. An untreated trajectory is shared across cases in a model.

## Protocol and preserved state

| Pulse | Stimulation | Subsequent rest |
|---|---|---|
| 1 | 50–100 | 100–160 |
| 2 | 160–220 | 220–290 |
| 3 | 290–360 | 360–440 |
| 4 | 440–520 | 520–610 |
| 5 | 610–700 | 700–800 |
| 6 | 800–900 | 900–1010 |

As in the repeated-input MATLAB script, calibration uses the complete untreated
0–1010 trajectory. Upward stimulation is 100 times the input maximum; downward
stimulation is one hundredth of its smallest strictly positive sampled value.
This avoids treating negative numerical tails as meaningful negative clamp
concentrations. Raw minima and zero clamp levels are retained in the report.
Zero-level cases are computed and flagged, although the MATLAB classification
skips them. A zero stimulus cannot demonstrate the absence of learning capacity.

Each pulse resets its input every 0.1 native time units, including its onset and
withdrawal: **4,506 resets** in a complete repeated history. All other state,
the absolute clock, native events and delay history remain continuous. The
original XML documents are unchanged. The implementations and independent
engines are those described in the retention guide: RoadRunner/COPASI for 34
models and method of steps/JiTCDDE for the Scheper delay model. Every stimulated
delay trajectory also receives a smaller-step, narrower-jump refinement.

## Validated results

The run evaluates 3,228 repeated or isolated-pulse branches plus 35 untreated
controls. Including delay refinements and the timed-drive equivalence check,
**3,313 full-trajectory comparisons pass**. The largest normalized discrepancy
is **0.90470** (acceptance limit 1), for Rohwer's `EIICB__up` isolated sixth pulse.
Source-code hashes, all 35 original XML hashes and successful worker exits were
checked after the run.

There are 4,680 input/direction/response assessments and 28,080 pulse-level
classifications. At the sixth pulse, the controlled increment categories are:

| Category | Response assessments |
|---|---:|
| No 1.5-fold change | 1,237 |
| Enhanced | 214 |
| Attenuated | 715 |
| Attenuated to unresolved | 852 |
| Reversed | 404 |
| Unresolved | 1,177 |
| Threshold unresolved | 58 |
| Response after history | 16 |
| Negative response state | 7 |

Eight response assessments encounter negative values beyond tolerance in at
least one pulse; seven do so in the last comparison. Twenty-two input cases
have a zero reset level and are explicitly marked. These results are numerical
protocol outcomes, not frequencies of biological learning or clinical drug
resistance.

For comparison, literal MATLAB branch logic labels 1,093 assessments resistant
and 747 sensitized in the first engine. At least one raw MATLAB field differs
between engines for 175 assessments. These raw labels have no resolution guard;
all controlled categories agree. They should not be substituted for the
controlled counts or represented as independently agreed historical labels.

## What the response comparisons mean

The report retains the MATLAB branch logic as `matlab_pulse_codes`,
`matlab_resistance` and `matlab_sensitization`. These use 1.5-fold changes in
successive stimulation-window means. There is an asymmetry in the source: an
initial downward response receives code 2, but a later further decrease receives
code 1. The implementation retains that behavior explicitly. The sampled windows
and SBML state inventory differ from the historical MATLAB arrays, so these are
MATLAB-style scores, not a claim of bitwise reproduction of the original labels.

Increasing absolute response levels can reflect accumulation or longer pulses.
For that reason the report separately compares each repeated pulse with the
same pulse in isolation. For response means `on` and preceding-rest means `pre`,
it records both:

```text
history effect on level = repeated_on - naive_on
history effect on increment = (repeated_on - repeated_pre) - (naive_on - naive_pre)
```

The operational categories distinguish enhanced or attenuated increments,
reversals, responses appearing only after history, and unresolved comparisons.
They require a 1.5-fold change outside a numerical-resolution band. That band is
four times `1e-7 + 2e-5 * max(abs(the four means))`; it is not a confidence interval.
Tiny responses and values close to a fold threshold remain unresolved.
Both engines must agree on each pulse's category, as well as on trajectories.
Raw MATLAB-label differences remain visible separately.

Negative response values beyond the mixed tolerance receive the separate
`negative_response_state` category. Strong forcing can drive a reduced model
outside the nonnegative domain of physical concentrations even when both
simulators agree. Such trajectories cannot be interpreted as biological
habituation or sensitization without addressing that model limitation.

## Sampling and numerical validation

The default grid contains 101,001 samples, spaced by 0.01 units except that
samples exactly coinciding with a possible reset are moved to the actual time
`reset + 0.00001`. Every arm, including untreated and isolated-pulse controls,
uses the same grid. The larger offset than in the retention screen avoids
event-root rounding near fast transients at late absolute times. It changes
observation times, not reset times, equations or comparison tolerances.

All observables at all samples must satisfy:

```text
abs(a - b) <= 1e-7 + 2e-5 * max(abs(a), abs(b))
```

Integration settings start from the validated retention reports. Rohwer retains
tighter RoadRunner integration than COPASI. Its `HPrPIIA__down` case uses COPASI
`rtol=1e-7`, `atol=1e-9`, because the ordinary request returned a partial
trajectory in an isolated-pulse control. Every branch records its settings and
must pass the unchanged full-trajectory comparison.

The Yoon signaling model (network 26, BioModel 664) needs `atol=1e-18` in both
engines to resolve small residuals that affect late responses; `rtol=1e-12`
remains unchanged. At that precision, crossing its discontinuous input rules
can exhaust step limits. A [hash-guarded encoding](grn_memory/timed_drives.py)
expresses the same drives as events: `g1=0, g2=1` initially, `g1=1, g2=0` at
time 5, and `g1=0` at time 10. This equivalence is for times at or after zero.
Other rules and reactions are preserved; the original XML is unchanged. Both
simulators compare the encoded untreated trajectory with the original across
the full observation window, and tests check values on both sides of each
switch. The transformed document hash is recorded. This representation change
does not change the model's dynamics or loosen acceptance.

The summaries are **arithmetic sample means**, following the type of statistic
used by the MATLAB code. They are not converged quadrature estimates of
continuous-time averages. In a two-input Rohwer pilot, changing the post-reset
offset from `1e-6` to `1e-5` changed some fast-state means by about 0.7%, although
all response categories and raw pulse codes were unchanged. Halving the grid
spacing to 0.005 also preserved those pilot classifications. These limited
checks do not establish sampling independence for the entire catalog.

## Reproduce

From `python/`:

```sh
uv sync --locked --extra test --extra delay
uv run --locked --extra test --extra delay python -m pytest -q
uv run --locked --extra delay python -m grn_memory.catalog_repeated --workers 3 --resume
```

The [runner](grn_memory/catalog_repeated.py) writes per-model checkpoints and an
aggregate `results/catalog-repeated/report.json`. It records source hashes,
model hashes, versions, calibration, every control branch, observed minima and
maxima, classifications and numerical discrepancies. Resume reuses passed
cases only with matching provenance. Each model has its own process and log.

For sampling checks, select a model and use `--sample-dt 0.005` or
`--post-reset-offset 0.000001`, with a separate `--output` directory.
`--limit-cases` and `--case` are diagnostic selections; their reports remain
incomplete and their commands exit nonzero unless the entire model is covered.
The full repeated-input run evaluates 3,228 stimulated/control branches in
addition to 35 untreated controls, before delay refinements.

Breaking acquired responses remains a further catalog stage. The
[paired-learning, transfer and delayed-cue screen](CATALOG_PAIRED.md) is running.
None of these operational screens alone
establishes clinical drug resistance or the original study's memory prevalence.
