# Complete Ciliberto failure inventory

This preparation covers **all 74 failed cases** in the original 622-case
network-28 search. It does not claim additional recovered cases or a whole-model
pass. The model is **BIOMD0000000697**, Ciliberto's 2003 Cyclin E/Cdk2 timer for
the cell cycle of the *Xenopus laevis* embryo. The original result remains
548/622 passing cases with 89 unresolved conditional decisions.

The [inventory](inventory.json) contains **7,334 distinct control branches**.
The previously published two-case recovery supplies 215 branches; all 860 saved
trajectories were read again and its complete audit reproduced exactly. The
remaining scope is **7,119 branches and 28,476 integrations**. These integrations
have not been dispatched by this preparation.

## Why the complete inventory is larger than the original failures

An initial case specifies a repeated training input, an attempted breaker and
eligible responses. Each trial needs eight matched controls: prior training
present or absent, breaker present or absent, and final cue present or absent.
If a response persists, the algorithm can repeat the breaker and then try a
different third breaker. The new trajectories can change which conditional path
is taken, so the inventory includes every possible continuation for the selected
cases. Identical branch specifications share one computation.

The old case-control preparation required every potential branch to already
appear in the original records. That requirement works for the published two
cases, but four other cases have **200 potential branches absent from every
original partition**. The new compiler generates those specifications from the
unchanged candidate plans and calibration. They remain uncomputed work; no
original measurements are invented or filled in.

| Case | Potential branches absent from its original partition |
|---|---:|
| `Kin_a__up--PCdk2_CycE__up` | 92 |
| `PCdk2_CycE__up--Kin_a__up` | 92 |
| `PCdk2_CycErem__up--Kin_a__up` | 8 |
| `Xic_PCdk2_CycE__up--Deg_a__up` | 8 |

The full original evidence contains 270 failed branch specifications:
259 integrations reporting an unexpected output shape, and eleven completed
solver disagreements. The output-shape errors are retained as errors; this
inventory does not establish their cause. Ten of these 270 branches already
have verified full arrays in the published two-case recovery.

## Fixed computation stages

The [computation plan](computation-plan.json) first selects all **260 remaining
original failed branches**, distributed deterministically over 32 partitions of
eight or nine branches. This requests 1,040 integrations. A second stage retains
all **6,859 remaining controls and potential continuations**, requiring 27,436
integrations. Neither stage can promote a case without the complete 74-case
audit, including all required controls, the full untreated baseline and replay
of the primary and refined conditional searches.

All four requests match the published recovery:

| Trajectory | Relative tolerance | Absolute tolerance |
|---|---:|---:|
| RoadRunner | `1e-13` | `1e-15` |
| RoadRunner refined | `5e-14` | `5e-16` |
| SciPy Radau | `1e-10` | `1e-12` |
| SciPy Radau refined | `1e-11` | `1e-13` |

Every full trajectory retains the original observation grid and reset schedule,
with horizons through 1,410, 1,810 or 2,210 time units and 20 observables. All six
pairwise comparisons use unchanged acceptance tolerances `2e-5` and `1e-7`.
Original passing native records are preserved as historical evidence. They are
not substituted for the four requested arrays in this selected-case computation.

The execution wrapper and a complete-case auditor that accepts explicitly new
potential branches are still required. The original numerical solvers and
case-audit mathematics have not been changed. No local stopped worker was used.

## Reproduce the preparation

The [verification record](verification.json) binds the inputs, scripts and
output checksums. A fresh download of the original 618,700,882-byte
[release asset](https://github.com/m9h/GRN_ODE/releases/download/kinetics-breaking-12-28-31-20261113/breaking-network28-20261113.tar.gz)
verified all 588 members. The unchanged sixteen-partition auditor reproduced the
original 622-case result, excluding only the extraction-directory names from
the equality check. Original source revisions, all case decisions and all
54,904 branch records were checked. The original release contains comparison
and window records, not raw trajectories.

Use this branch in a full clone. From `python/`, first follow the
[published two-case reproduction guide](../catalog-breaking-ciliberto-case-recovery-20261118/RELEASE.md)
using its unchanged reproducer in this checkout. Keep its assembled output.
Then run:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
gh release download kinetics-breaking-12-28-31-20261113 --repo m9h/GRN_ODE \
  --pattern breaking-network28-20261113.tar.gz --dir results/ciliberto-original-download
uv run --locked --extra test --extra jaxkineticmodel python scripts/prepare_ciliberto_full_inventory.py \
  --archive results/ciliberto-original-download/breaking-network28-20261113.tar.gz \
  --recovery results/ciliberto-release-reproduction/assembled \
  --output results/ciliberto-full-inventory-reproduction
uv run --locked python scripts/plan_ciliberto_full_computation.py \
  --inventory results/ciliberto-full-inventory-reproduction/inventory.json \
  --output results/ciliberto-full-inventory-reproduction/computation-plan.json
```

Use new output directories. This performs no integrations. The original archive
needs about 1.3 GB for download and extraction in addition to the published
two-case reproduction's disk requirements. A fresh assembly timestamp changes
the reused report and audit hashes; case plans, branch specifications, requests,
branch selections and scientific outcomes must still agree exactly.

Local validation passes 38 targeted tests, including fourteen new inventory and
transport checks, plus workflow lint. The two-case inventory reproduces all
215 published specifications exactly. Tests also require all 74 failed cases,
eight controls per trial, complete stage assignments, rejection of omitted
controls and ambiguous original eligibility, and checksum-safe extraction.
The separate Linux validation workflow is pending; this preparation adds no
new scientific coverage.
