# Ciliberto selected-case evidence repair

The original producer finished all 215 control branches for two selected cases
on 14 November. Its unchanged report has SHA-256
`bc0559d9ce685676c45c8b6162f98236b1e35a7b878ba32ac165666eb893f342`.
That report alone does not establish a reproducible case recovery.

A fresh complete-array audit on 18 November failed because required local files
were absent: 18 branch records and 74 of the 860 required trajectory arrays.
The missing data affect 19 branches, including the full untreated baseline.
The cause of the missing files has not been established. The surviving 197
records and 786 arrays were preserved outside temporary storage; every available
record and array matches its recorded hash. The
[preservation manifest](preservation-manifest.json) records the files, sizes,
checksums and missing inventory. No additional case or whole-model recovery is
claimed from the incomplete data.

One affected branch was imported from the previously published
[ten-branch diagnostic](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-validation-20261112).
Its four original arrays and branch record have now been restored exactly:
the archive hash, all 40 archive members and the restored record's original hash
pass verification, with numerical integration disabled. The
[restoration proof](restoration-proof.json) records the result. This leaves 17
missing records and 70 missing arrays across 18 branches. The
[fixed recomputation plan](recomputation-plan.json) selects every other affected
branch, exactly 18, by missing evidence rather than numerical outcome. Each
selected branch is recomputed in full with the original two RoadRunner and two
Radau requests. Recomputed outputs are new calculations with explicit lineage;
they are not described as byte-identical restorations of the lost files.
The partially preserved branch is recomputed with all four requests, so the
fixed cloud plan produces 72 arrays. Its two surviving arrays remain in the
unchanged historical snapshot; no choice between old and new outcomes is made.

The original SBML model, all 215 branch specifications, both selected cases,
complete observation grids, reset schedules, solver tolerances and acceptance
thresholds remain fixed. All 18 bound numerical implementation files must match
the original producer, and all recorded numerical package versions must match
before computation. The new wrapper adds only input verification, fixed branch
selection and execution provenance. All four trajectories and all six pairwise
comparisons are retained, including failures. Existing passing or failing
evidence is never selected according to a preferred result.

From `python/`, validate the plan without numerical integration:

```bash
uv run --locked --extra test --extra jaxkineticmodel python scripts/recompute_ciliberto_evidence.py \
  --inputs results/catalog-breaking-ciliberto-case-recovery-20261118 \
  --plan-sha256 c5fe2486bfa6b2f531e95ab5f2cf06006b2089a01065f0ace568c0ef2d152814 \
  --check-only
```

The cloud workflow keeps four replacement jobs concurrent and retains every
original time horizon. The nine paused local numerical workers are not used.
After collection, all replacements, exact restored imports and unaffected
original branches must be assembled with their provenance and independently
audited across the full 215-branch inventory. The auditor must recompute every
comparison, window summary, conditional path and controlled classification.
Only that complete audit can establish recovery of these two selected cases.
The separate original full-model result remains 548/622 passing cases with 74
failures; these selected calculations cannot be added to that count ad hoc.

The new selection tests and existing complete-case auditor tests pass all 29
checks. The input-only preflight verifies all 18 original implementation hashes
and recorded package versions without integration. Workflow syntax also passes
`actionlint`. Linux validation must pass again before cloud computation starts.

To reproduce the exact published import without integrating any equations:

```bash
gh release download kinetics-validation-20261112 --repo m9h/GRN_ODE \
  --pattern ciliberto28-shard0-radau-trajectories-20261112.tar.gz --dir results
uv run --locked --extra test --extra jaxkineticmodel python scripts/restore_ciliberto_pilot_evidence.py \
  --inputs results/catalog-breaking-ciliberto-case-recovery-20261118 \
  --plan-sha256 c5fe2486bfa6b2f531e95ab5f2cf06006b2089a01065f0ace568c0ef2d152814 \
  --archive results/ciliberto28-shard0-radau-trajectories-20261112.tar.gz \
  --output results/restored-ciliberto-import
```
