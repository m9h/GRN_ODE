# Fuss: complete native refinement diagnostic

All 330 failed branches from the original completed breaking-memory search for
`BIOMD0000000069` have now been repeated with RoadRunner and COPASI at the
original tolerances, then tolerances divided by ten and twenty. All **1,980
integrations finish**, preserving the full original reset trains and observation
horizons. **Zero branches pass the declared refinement criterion.** This does
not recover a case or change the model's validation status.

The acceptance threshold remains `rtol=2e-5`, `atol=1e-7`. For every branch:

- COPASI's original-to-tight and tight-to-tighter comparisons pass.
- RoadRunner's original-to-tight and tight-to-tighter comparisons fail.
- RoadRunner and COPASI disagree at all three settings.

The largest normalized discrepancies are 0.932 for COPASI's final refinement,
7.391 for RoadRunner's final refinement, and 5.028 between the two engines at
the tightest settings; a comparison passes only at a value no greater than one.
COPASI's self-consistency alone cannot establish an independent reference.
The next useful check needs full saved arrays from another integration method
before a complete case recovery can be attempted.

`verification.json` independently checks the complete original failure
inventory, source/model hashes, all six requests per branch, sample counts,
window inventories and recorded comparison consistency. The original producer
did not retain raw trajectory arrays. This is therefore a provenance and
consistency verification, not an independent pointwise recomputation.

The [release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-fuss-refinement-20261114)
preserves every branch record and the complete captured source evidence.
`release-manifest.json` records archive and member checksums. Extract the
archive into a separate directory and, with the original completed-search
evidence available, run from `python/`:

```bash
uv run --locked python scripts/verify_breaking_refinement.py \
  --input /path/to/catalog-breaking-fuss8-refinement \
  --source-report results/catalog-breaking-original-completed-20261112/BIOMD0000000069.json \
  --source-revision 70a3afad61357e94873ff62a7300c099b4c7ae3e \
  --producer-revision c3066a6d171ae7602d3699098ea811c3d3da4871 \
  --output /tmp/fuss-refinement-verification.json
```

The diagnostic producer revision identifies source files whose hashes match
the completed run; its numerical implementation stayed frozen throughout.
