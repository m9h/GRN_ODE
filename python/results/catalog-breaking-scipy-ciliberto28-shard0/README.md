# Full-array Ciliberto branch diagnostic

All ten captured failed branches from network 28's first sixteen-way partition
complete under two RoadRunner and two SciPy Radau requests. All 60 pairwise
comparisons pass, with maximum scaled error 0.007803290993178095 (limit one).
Every integration retains all 221,001 samples over 0–2210, 20 observables,
and its original reset schedule. The report records the equations, versions,
requests and source hashes. The separate auditor recomputes the comparisons
and window means from the arrays.

This is a branch diagnostic. It does not recover the two full failed cases,
whose remaining controls and conditional continuations require validation,
or establish complete coverage of the 622-case model.

The 40 compressed NPZ arrays are distributed as a separate release asset.
Download the asset from [the validation release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-validation-20261112), verify its SHA-256 against `download.json`, and extract it from `python/results/`. The archive contains only the paths listed in that manifest. Reports and audit code are tracked separately in Git.

From `python/`:

```bash
gh release download kinetics-validation-20261112 --repo m9h/GRN_ODE \
  --pattern ciliberto28-shard0-radau-trajectories-20261112.tar.gz --dir results
shasum -a 256 results/ciliberto28-shard0-radau-trajectories-20261112.tar.gz
# Expected: 268cf3352ae515379b7ab3dabba712fdec80b379c8d6ed2974dc5fb71210eb28
tar -xzf results/ciliberto28-shard0-radau-trajectories-20261112.tar.gz -C results
MPLBACKEND=Agg uv run --locked --extra jaxkineticmodel python scripts/audit_scipy_breaking.py \
  --input results/catalog-breaking-scipy-ciliberto28-shard0 \
  --output results/catalog-breaking-scipy-ciliberto28-shard0/audit.json
```

The asset's SHA-256 and every archive member were verified before publication.
`download.json` records all member paths, sizes and hashes. It is approximately
921 MB; the archive of native network-8/12/30 evidence is a separate download.
