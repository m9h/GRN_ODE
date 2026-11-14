# Fuss: independent Radau/COPASI reference check

The completed native refinement diagnostic found 330 unresolved branches:
COPASI passed both self-refinement comparisons on every branch, while
RoadRunner failed both and disagreed with COPASI at all three settings. A
second integration method is needed before treating either as a reference.

This pilot uses the original model and full protocols with COPASI and SciPy's
Radau solver, using Jaxkineticmodel equations and a JAX-derived Jacobian.
The native reference is an explicit command-line choice, included in the
configuration fingerprint, package inventory and independent array audit.
It is never switched automatically after a mismatch. RoadRunner remains the
default for existing workflows on their frozen source revisions.

`plan.json` selects the first, middle and last records after sorting all 330
native refinement records by tightest cross-engine normalized error, then
record ID. Selection is declared before these new integrations run. Every
selected trajectory keeps all 221,001 observations over time 0–2210:

| Record prefix | Original tightest discrepancy | Resets |
|---|---:|---:|
| `01171aa41819e` | 1.2846 | 10,500 |
| `6bc353163b98` | 1.8932 | 9,501 |
| `acc8a1cc63c1` | 5.0277 | 10,500 |

COPASI requests are `(rtol, atol)=(1e-13,1e-15)` and `(5e-14,5e-16)`.
Radau requests are `(1e-11,1e-13)` and `(1e-12,1e-14)`. All six pairwise
comparisons must pass the unchanged acceptance rule `(2e-5,1e-7)`. Full
binary64 arrays are saved; the independent auditor recomputes all comparisons
and rejects missing samples, changed solver identities and incomplete resets.

This is a selected-branch diagnostic, not a complete 330-branch rerun or a case
recovery. A successful pilot would support the subsequent full control and
conditional-search validation. It does not change the original 314/332 case
result, and a failed result will remain recorded.

## Reproduce

Download and extract `catalog-breaking-fuss8-refinement-20261114.tar.gz` from
the [complete native diagnostic release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-fuss-refinement-20261114).
Its `source-evidence.json` is the input below; `plan.json` records its checksum.
From `python/`, use a fresh output directory:

```bash
uv sync --locked --extra test --extra jaxkineticmodel
uv run --locked --extra jaxkineticmodel python scripts/diagnose_scipy_breaking.py \
  --evidence /path/to/catalog-breaking-fuss8-refinement/source-evidence.json \
  --output results/catalog-breaking-fuss-radau-pilot \
  --reference-engine copasi --reference-rtol 1e-13 --reference-atol 1e-15 \
  --rtol 1e-11 --atol 1e-13 \
  --branch 01171aa41819eae5e6712132ef080e0c555c264d8b2a92c3dc788ac6fa631075 \
  --branch 6bc353163b986c9fb0ebe2de5b737433d659d295f5c3042983312100df7d2e38 \
  --branch acc8a1cc63c117c2fb3da37cdb58d3249dd3fa743fd59f113fafbac9c16bf412
uv run --locked --extra jaxkineticmodel python scripts/audit_scipy_breaking.py \
  --input results/catalog-breaking-fuss-radau-pilot \
  --output results/catalog-breaking-fuss-radau-pilot/audit.json
```

`--resume` reuses only complete integrations after checking the unchanged
configuration and every saved array. Switching native engines requires a new
output directory. The original live workers use other checkouts and are
unaffected by this explicit reference selection.

Validation: 81 diagnostic, array-auditor, control-runner and complete-case
auditor tests pass. One COPASI-specific environment check is skipped only for
the RoadRunner fixture; it runs for the COPASI fixture. Tests cover native
dispatch, refusing engine changes on resume, all six full-array comparisons,
missing package provenance, changed final samples and lower-precision arrays.
The synthetic test fixtures are not simulation results.
