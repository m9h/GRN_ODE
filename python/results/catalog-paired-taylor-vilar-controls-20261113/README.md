# Vilar controls for complete paired-case validation

This plan covers the three Vilar cases still unresolved after the separate
SciPy/RoadRunner recovery audit: `DAp__up--DR__up`, `DAp__up--DRp__up` and
`DAp__up--MR__up`. It does not claim a numerical recovery. The existing result
remains 139 of 142 validated Vilar paired cases until complete evidence supports
a change.

Each case has twelve arms: untreated, UCS-only, CS-only and joint training,
each followed by a sham, normal-time cue or delayed cue. Sharing identical arms
across cases leaves **32 distinct full trajectories**. Nine belong to the
existing 16-failed-branch Taylor batch; this complementary batch supplies the
other **23 controls**. The untreated `none_sham` control covers all 300 time
units. The existing 0–50 baseline diagnostic cannot replace it.

`plan.json` is reconstructed from the original paired report, branch archive,
calibration, candidate cases and source revision. It records every selected
case, arm, reset schedule, source digest and the mapping to the existing failed
partitions. Model 35 is BioModels **BIOMD0000000035**, the Vilar circadian
oscillator, numbered **32** in the original 35-network catalog.

Every branch keeps all 30,001 observations, the original intervention clocks
and reset values. The numerical requests match the failed-branch batch:

| Integration | Request |
| --- | --- |
| Heyoka Taylor | 128-bit arithmetic, tolerance `1e-30` |
| Heyoka Taylor | 192-bit arithmetic, tolerance `1e-45` |
| RoadRunner | relative tolerance `1e-13`, absolute tolerance `1e-15` |

All three pairwise trajectory comparisons use the original acceptance rule,
relative tolerance `2e-5` and absolute tolerance `1e-7`. The two Taylor runs
check precision convergence; RoadRunner provides the independent integrator.
Matching rounded trajectories at these settings is numerical evidence, not a
proof of exact solutions or of cognition.

The case auditor reads the full saved arrays from both batches, checks source
and environment identity, recomputes comparisons, and recomputes the window
means and controlled memory classifications. Every arm uses the same three
integrations. An incomplete arm, a failed comparison or a disagreement in a
controlled classification prevents case recovery. Literal paper-style labels
remain separately visible when they differ near numerical thresholds.

## Reproduce the plan

From `python/`, using the project's uv environment:

```bash
uv run --locked python scripts/run_taylor_case_control.py plan \
  --model 35 --case DAp__up--DR__up --case DAp__up--DRp__up \
  --case DAp__up--MR__up --output /tmp/vilar-control-plan.json
```

For a Linux precision environment, follow
[the existing uv installation instructions](../../PRECISION_DIAGNOSTICS.md#separate-environment).
Compute one of the 23 partitions with:

```bash
uv run --no-project --python .venv-taylor/bin/python python \
  scripts/run_taylor_case_control.py run \
  --plan results/catalog-paired-taylor-vilar-controls-20261113/plan.json \
  --partition-index 0 --partition-count 23 \
  --output results/taylor-control-0 --max-seconds 14400
```

Use `--resume` with the same directory after a checkpoint stop. Sources must be
committed and match the recorded source hashes. Completed integrations and
exact MPFR checkpoints are verified before reuse. A checkpoint stop is recorded
separately from an integration failure.

The `precision-case-controls.yml` workflow runs analytic, coverage and artifact
restoration tests before computing all controls. It uses uv, pins Python and
Heyoka, and preserves full arrays and checkpoints in each artifact. An optional
`resume_run` restores only a completed matching parent job after verifying its
run, commit, plan, archive digest, arrays and checkpoint state.

Audit all 32 completed branches, supplying each directory once:

```bash
uv run --locked python scripts/run_taylor_case_control.py audit \
  --plan results/catalog-paired-taylor-vilar-controls-20261113/plan.json \
  --input /path/to/first-complete-branch \
  --input /path/to/second-complete-branch \
  --output results/vilar-taylor-case-audit.json
```

Continue the `--input` list for the remaining branches. `--allow-partial` can
report available evidence and explicit missing arms; it never promotes a case
with missing or unconfirmed controls. The files in this directory are a plan,
not evidence that the 23 computations have finished.
