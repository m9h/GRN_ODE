# Ueda complete-case recovery inventory

The original Ueda circadian-clock search (BioModels **BIOMD0000000022**, catalog network 11) evaluates 302 cases and validates 298. Its four remaining cases are `CCn__down--CCc__up`, `CCn__down--Clkc__up`, `Perm__down--Perc__up`, and `Timm__down--Timc__up`.

A separate full-array diagnostic now confirms all 24 previously mismatched trajectories using RoadRunner and SciPy Radau, with an additional tolerance refinement of each. This is trajectory evidence; complete-case recovery still requires controls and replay of every conditional decision.

The captured original cases contain 298 distinct trajectories. Three cases stop after 16 trials; the fourth contains 18. Each case has 18 possible trials under the unchanged original candidate definitions. A new solver comparison can change a continuation decision, so the recovery inventory includes **24 additional candidate trajectories**, plus the full untreated trajectory over 0–2210. The complete computation therefore covers **323 distinct trajectories**, with four integrations and six pairwise comparisons in each. The 24 already audited failed trajectories can be reused after provenance and array checks; the remaining 299 require computation.

All original eligibility definitions, model equations, reset trains, prior rechallenges, observation grids and comparison thresholds are retained. Later trajectories contain 221,001 samples over 0–2210; earlier trajectories use their original shorter trial horizons. No case is recovered by this inventory. The final auditor must verify all arrays, replay the conditional searches, compare classifications across solvers and refinements, and record any disagreement with previously passing original evidence.

`original-case-plan.json` and `source-branches.jsonl.gz` preserve the original selected records; `source-branches-provenance.json` binds them to every original archive hash. `source-evidence.json` contains the original model report and 24 failed trajectories' summary records. `inventory.json` reconstructs all candidate branches and explicitly names the 24 newly required branch IDs.

The inventory code now accepts an original conditional search that stopped before all possible later trials. It still rejects missing original controls, missing cases, changed resets, altered provenance, and original branches outside the reconstructed candidate inventory. The live Ciliberto computation uses its unchanged source checkout.

Validation: 67 diagnostic, array-audit, control-inventory and case-audit tests pass, including the real Ueda early-stop inventory and rejection of removed controls, removed cases and changed resets. A fresh capture from all original archives reproduces the selected records and reconstructed inventory; gzip timestamps can change compressed-file provenance hashes without changing the records.

## Reproduce

Use this branch's pinned source and uv environment. Extract the [original Ueda archive release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-ueda-diagnostics-20261113) into `python/results`; its `catalog-breaking-ueda11-local/evidence` directory complements the original report already tracked in `results/catalog-breaking-ueda11-local/BIOMD0000000022.json`. From `python/`, reconstruct the inventory in a fresh directory:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
uv run --locked --extra test --extra jaxkineticmodel python \
  results/catalog-breaking-ueda11-case-plan-20261114/capture_original_cases.py \
  --source . --original results/catalog-breaking-ueda11-local \
  --evidence results/catalog-breaking-ueda11-case-plan-20261114/source-evidence.json \
  --revision 70a3afad61357e94873ff62a7300c099b4c7ae3e \
  --output /path/to/fresh-ueda-case-plan
```

After unpacking the [completed full-array diagnostic](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-ueda-radau-20261114), run the complete controls:

```sh
MPLBACKEND=Agg uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/diagnose_scipy_breaking_controls.py \
  --evidence results/catalog-breaking-ueda11-case-plan-20261114/source-evidence.json \
  --case-plan results/catalog-breaking-ueda11-case-plan-20261114/original-case-plan.json \
  --original-branches results/catalog-breaking-ueda11-case-plan-20261114/source-branches.jsonl.gz \
  --source-revision 70a3afad61357e94873ff62a7300c099b4c7ae3e \
  --diagnostics /path/to/catalog-breaking-scipy-ueda11 \
  --output results/catalog-breaking-scipy-ueda-cases
```

Once the computation finishes, run `scripts/audit_scipy_breaking_cases.py` with `--input results/catalog-breaking-scipy-ueda-cases --output results/catalog-breaking-scipy-ueda-cases/audit.json` in the same uv environment. A branch diagnostic or successful software test alone cannot increase the model's validated-case count.
