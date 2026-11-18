# Vilar partition 6: precision convergence with a retained native mismatch

The [completed cloud branch](https://github.com/m9h/GRN_ODE/actions/runs/44247017097)
for BioModel **BIOMD0000000035** (network **32**) retains three full trajectories:
128-bit Taylor integration, 192-bit Taylor integration and RoadRunner. Each has
30,001 observations from time 0 through 300, across ten observables, with all
499 original resets between times 50 and 100. No horizon, reset, observation
or acceptance threshold has been shortened or relaxed.

| Full-array comparison | Maximum scaled error | Result |
| --- | ---: | --- |
| Taylor 128 versus Taylor 192 | 0 | Pass |
| Taylor 128 versus RoadRunner | 2.0546768658 | Mismatch retained |
| Taylor 192 versus RoadRunner | 2.0546768658 | Mismatch retained |

For each observable and time, scaled error is
`abs(x-y) / (1e-7 + 2e-5 * max(abs(x), abs(y)))`.
Every observation must have scaled error at most 1. The largest scaled native
discrepancy occurs in **A at time 92.53**. Across all observations, the largest
absolute difference is 0.2158592241.

The Taylor requests use 128 bits with tolerance 1e-30 and 192 bits with tolerance
1e-45. RoadRunner uses relative tolerance 1e-13 and absolute tolerance 1e-15.
Taylor agreement here means the saved binary64 observations are identical; it
does not assert that the internal high-precision states or exact solutions are
identical. Agreement under precision refinement supports convergence of this
implementation. The independent native discrepancy remains part of the finding.

The source experiment requires seventeen partitions, including the untreated
baseline. This package covers partition 6 only and does not establish recovery
of any complete memory case. Four remaining partitions continue in
[run 44384045755](https://github.com/m9h/GRN_ODE/actions/runs/44384045755); the aggregate
paired-validation count remains 4,205/4,208.

## Reproduce from the original artifact

The release tag is `kinetics-vilar-partition6-20261118`. Publication and
fresh-download status are recorded in its release notes. The ZIP is the original
9,990,685-byte GitHub artifact, with SHA-256
`26e4d201fc691cfc32e410b8102bf6b5ebc6034de2acdf7ea5f88b1ad2f6edbb`.
The [fixed selection](selection.json), [original API snapshot](api),
[producer report](report.json), [execution record](execution.json) and
[complete audit](audit.json) bind the result to its source and execution.

From a full clone of this repository:

```sh
git checkout kinetics-vilar-partition6-20261118
cd python
uv sync --locked --extra test
gh release download kinetics-vilar-partition6-20261118 --repo m9h/GRN_ODE --dir results/vilar-partition6-download
uv run --locked --extra test python results/catalog-paired-vilar-partition6-20261118/reproduce.py \
  --asset results/vilar-partition6-download/vilar-partition6-artifact-14408884503.zip \
  --output results/vilar-partition6-reproduction
```

The output directory must be new. The reproducer verifies the exact ZIP,
every extracted file, original protocol and source identities, all three full
arrays and all three comparisons. Its complete audit JSON must equal the saved
audit, including the native mismatch. It performs no integrations and does not
require a local Heyoka installation.
