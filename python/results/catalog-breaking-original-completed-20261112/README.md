# Completed original searches for networks 8, 12 and 30

These are full conditional searches at original producer revision
`70a3afad61357e94873ff62a7300c099b4c7ae3e`. The audit covers 586 cases,
553 passing cases and 30,493 branches. All integrations finish, but 369
branches retain trajectory mismatches. None of these three reports establishes
full numerical validation. Network 30 also has a separate Linux result.

The 315 compressed public branch/case archives are distributed separately to
keep large evidence files out of Git. They contain recorded comparisons and
window summaries, not full raw trajectory arrays or restart checkpoints.
`source-files.json` preserves each copied source file's hash.

Download the asset from [the validation release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-validation-20261112), verify its SHA-256 against `download.json`, and extract it from `python/results/`. The archive contains only the paths listed in that manifest. Reports and audit code are tracked separately in Git.

From `python/`:

```bash
gh release download kinetics-validation-20261112 --repo m9h/GRN_ODE \
  --pattern breaking-8-12-30-20261112.tar.gz --dir results
shasum -a 256 results/breaking-8-12-30-20261112.tar.gz
# Expected: b5e39c21888fcd3e0f0b0e9c136108107acc99f580ebce65f83b025e0e03f7f5
tar -xzf results/breaking-8-12-30-20261112.tar.gz -C results
MPLBACKEND=Agg uv run --locked python scripts/audit_breaking_catalog.py \
  --input results/catalog-breaking-original-completed-20261112 \
  --source-revision 70a3afad61357e94873ff62a7300c099b4c7ae3e \
  --network 8 --network 12 --network 30 \
  --output results/catalog-breaking-original-completed-20261112/audit.json
```

The source revision must be available in local Git history. A successful
evidence audit verifies the reported failures as well as the passes; it does
not convert numerical disagreement into a passing model.
