# Ueda native-solver refinement

All 144 integrations finish for the 24 original mismatched branches. Sixteen
branches pass both refined cross-engine comparisons and each engine's further
refinement; eight do not. The requests are the original `1e-12/1e-14`, then
`1e-13/1e-15` and `5e-14/5e-16` for both RoadRunner and COPASI.

Every branch retains all 221,001 observations over 0–2210 and the original
reset schedule. Acceptance stays `rtol=2e-5, atol=1e-7`. Disagreements are not
necessarily monotone in the requested tolerances. No complete cases are
recovered by this branch diagnostic.

`verification.json` checks the full original failed-branch inventory against
the independently audited [complete local search](../catalog-breaking-ueda11-local/README.md),
source hashes, integration requests, observations and recorded comparisons.
This producer saves comparison records and window summaries, not raw arrays;
verification cannot independently recompute pointwise errors. The
[additional Radau/RoadRunner computation](../catalog-breaking-ueda11-diagnostic-plan-20261113/README.md)
saves full arrays and is audited separately after it finishes.

To reproduce the native computation from `python/`, use a fresh directory:

```bash
MPLBACKEND=Agg uv run --locked python scripts/diagnose_breaking_refinement.py \
  --evidence results/catalog-breaking-ueda11-refinement/source-evidence.json \
  --output results/catalog-breaking-ueda11-refinement-reproduction
```

After downloading the complete local evidence using its README, verify the
published diagnostic without reintegrating:

```bash
uv run --locked python scripts/verify_breaking_refinement.py \
  --input results/catalog-breaking-ueda11-refinement \
  --source-report results/catalog-breaking-ueda11-local/BIOMD0000000022.json \
  --source-revision 70a3afad61357e94873ff62a7300c099b4c7ae3e \
  --producer-revision 92ca96912effeba7886fb78e9bb64ab084babb82 \
  --output results/catalog-breaking-ueda11-refinement/verification-reproduction.json
```

The verifier distinguishes consistent failure evidence from confirmed
refinement. A successfully verified report can still contain failed branches.
