# Ueda full-array diagnostic plan

The complete original Ueda search has 302 cases, of which 298 pass. All
integrations finish, but 24 distinct branches have numerical mismatches.
`source-evidence.json` captures the original report, those 24 branch records
and the checksums of the source archives. `plan.json` binds the full selected
inventory to the unchanged model, diagnostic sources and package versions.

The RoadRunner/COPASI refinement diagnostic retains some disagreements after
tightening both tolerances. The additional computation therefore saves full
arrays from RoadRunner at `1e-14/1e-16` and `5e-15/5e-17`, and Radau at
`1e-11/1e-13` and `1e-12/1e-14`. Each branch retains all 221,001 observations
over 0–2210, every species and every original reset. The comparison acceptance
stays `rtol=2e-5, atol=1e-7`.

The inventory requires 96 integrations and 144 pairwise comparisons. The
computation is running; the plan is not a result or a case recovery. A passing
branch diagnostic still needs the corresponding controls and complete
conditional search before a case can be recovered.

Reproduce from `python/` in a fresh output directory:

```bash
uv sync --locked --extra test --extra jaxkineticmodel
MPLBACKEND=Agg uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/diagnose_scipy_breaking.py \
  --evidence results/catalog-breaking-ueda11-diagnostic-plan-20261113/source-evidence.json \
  --output results/catalog-breaking-scipy-ueda11-reproduction \
  --reference-rtol 1e-14 --reference-atol 1e-16 --rtol 1e-11 --atol 1e-13
```

After the computation finishes, recompute every comparison from the saved
arrays and verify the full reset and observation evidence:

```bash
uv run --locked --extra test --extra jaxkineticmodel python scripts/audit_scipy_breaking.py \
  --input results/catalog-breaking-scipy-ueda11-reproduction \
  --output results/catalog-breaking-scipy-ueda11-reproduction/audit.json
```
