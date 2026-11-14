# Complete De Caluwe circadian-clock breaking screen

Network 20, `BIOMD0000000631` (DeCaluwe2016 – Circadian Clock), completes the
original conditional breaking-memory protocol with **484/484 passing initial
cases**. The independent evidence audit reconstructs all **4,704 conditional
trials**, **5,795 response-trials** and **18,579 distinct branches**. Every
branch comparison passes; there are no incomplete integrations, completed
mismatches, solver retries or unresolved conditional decisions.

This is a complete single-model result. Published terminal breaking reports
now cover 28 of the 35 models, with 23 fully passing numerical validation after
separate recoveries. Seven searches remain unfinished: networks 2, 5, 15, 25,
29, 32 and 35. The five completed models retaining numerical failures are
reduced Goldbeter, Fuss, Ueda, Ciliberto and Marhl.

## What was checked

The producer uses the unchanged original SBML and the original calibrated
interventions, reset schedule and conditional choice of later trials. RoadRunner
and COPASI are compared across every requested observable and sample, including
the untreated control, with acceptance `rtol=2e-5`, `atol=1e-7`. The full
three-trial observation horizon reaches 2210 model-time units with sampling
interval 0.01. A numerical pass does not mean every intervention restores
memory; the operational classifications and literal MATLAB-style decisions
are retained separately.

`audit.json` verifies the original source revision, model and reference hashes,
the exhaustive candidate inventory, all archived branch/case identities,
sample counts, comparisons, required controls and every conditional decision.
It reconstructs case scores from saved window summaries. The original worker
performed the pointwise cross-engine comparisons, but did not persist full
trajectory arrays for this catalog run. The audit therefore verifies recorded
numerical evidence and independently recomputes classifications; it does not
rerun integration or independently recompute pointwise errors from raw arrays.

The model report and 191 compressed evidence archives were copied only after
the producer finished, and every archive was checked against its recorded
SHA-256 digest. The [release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-decaluwe20-20261114)
preserves all of that evidence. `release-manifest.json` lists the release archive
and every member's size and SHA-256 digest.

## Reproduce the audit

Extract the release to a separate directory and run from this revision's
`python/` directory:

```bash
uv run --locked python scripts/audit_breaking_catalog.py \
  --input /path/to/catalog-breaking-decaluwe20-local-20261114 \
  --output /tmp/decaluwe20-audit.json \
  --source-revision 70a3afad61357e94873ff62a7300c099b4c7ae3e \
  --network 20
```

Expected: 484 passing cases, 18,579 passing branches, complete selected-model
conditional coverage, and `complete_catalog_initial_case_coverage: false`.
The last flag deliberately remains false because this audit covers one model.
See [`CATALOG_BREAKING.md`](../../CATALOG_BREAKING.md) for the protocol math,
control definitions and whole-catalog reproduction commands.
