# Ueda: all 24 failed trajectories pass independent full-array checks

The diagnostic completed **96 integrations** across all 24 originally mismatched trajectories of BioModels **BIOMD0000000022**, the Ueda circadian-clock model (catalog network 11). The independent auditor recomputed all **144 pairwise comparisons** from the saved numerical arrays, and every comparison passes the unchanged acceptance criterion (`rtol=2e-5`, `atol=1e-7`).

Each trajectory retains all **221,001 observations over 0–2210**, every observable, and the original reset train. Reset counts range from 4,995 to 10,500. RoadRunner uses `rtol=1e-14, atol=1e-16`, refined to `5e-15, 5e-17`; SciPy Radau uses `1e-11, 1e-13`, refined to `1e-12, 1e-14`. Radau evaluates the Jaxkineticmodel equations and a JAX-derived Jacobian while preserving absolute time across resets.

| Comparison | Largest scaled error across all 24 trajectories |
| --- | ---: |
| RoadRunner vs refined RoadRunner | 0.780040 |
| RoadRunner vs Radau | 0.358502 |
| RoadRunner vs refined Radau | 0.437901 |
| Refined RoadRunner vs Radau | 0.421540 |
| Refined RoadRunner vs refined Radau | 0.342142 |
| Radau vs refined Radau | 0.079399 |

The pass threshold for each scaled error is 1. Both cross-method agreement and each method's tolerance refinement are checked. These results do not erase the original RoadRunner/COPASI mismatches, prove an exact mathematical solution, or recover complete cases by themselves.

The original result remains **298/302 validated breaking cases**. A separate complete-case computation must include every control and possible conditional continuation, then verify classifications and agreement with original passing evidence before any recovery is accepted.

## Evidence and reproduction

`report.json` records all original requests and provenance; `audit.json` recomputes the pointwise comparisons and retains window summaries for later case auditing. `source-evidence.json` binds the original model report and all 24 failed branch records to their source archive hashes. The original producer revision is `70a3afad61357e94873ff62a7300c099b4c7ae3e`.

The [evidence release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-ueda-radau-20261114) contains all 96 full trajectory arrays, all branch records, source evidence and this audit. The separate manifest records every packaged file's hash and the archive digest. Use the source revision pinned by the release, extract the bundle, and run from `python/`:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
uv run --locked --extra test --extra jaxkineticmodel python scripts/audit_scipy_breaking.py \
  --input /path/to/catalog-breaking-scipy-ueda11 \
  --output /path/to/recomputed-ueda-audit.json
```

Compare the recomputed JSON with the packaged `audit.json`; it should match exactly. This command audits saved arrays without rerunning integration. The producer used JAX/jaxlib 0.12.0.1, Jaxkineticmodel 0.0.1, SciPy 1.18.1, NumPy 2.5.4, pandas 3.1.1, libroadrunner 2.11.0 and python-libsbml 5.21.2; the report also records Diffrax and Equinox versions and all implementation hashes. The original [diagnostic plan](../catalog-breaking-ueda11-diagnostic-plan-20261113/README.md) gives the full integration command.
