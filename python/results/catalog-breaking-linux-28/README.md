# Complete network 28 breaking search

All 622 initial cases were evaluated; 548 pass
numerical validation. The audit reconstructs 13663 conditional
trials, 44912 response-trials and 54904
branch records (54344 distinct specifications).
There are 89 unresolved conditional decisions.
Numerical validation is separate from whether a case exhibits a resolved memory effect.

Workflow: [43370478631](https://github.com/m9h/GRN_ODE/actions/runs/43370478631).
`source-artifacts.json` preserves producer revisions, artifact digests and file hashes.
Every partition retains its own shared controls. Reports and the combined audit
are tracked in Git; the release contains the referenced compressed evidence and
any parent-resume metadata. It excludes hidden restart-cache duplicates.

These archives contain recorded pointwise comparisons and window summaries,
not full raw trajectory arrays. The independent audit verifies every record,
reconstructs the conditional search and recomputes scores without reintegration.

From `python/`, with the producer revisions available in local Git history:

```bash
gh release download kinetics-breaking-12-28-31-20261113 --repo m9h/GRN_ODE \
  --pattern breaking-network28-20261113.tar.gz --dir results
shasum -a 256 results/breaking-network28-20261113.tar.gz
# Expected: 879180f5b4c4f543deab6f3f366837a65023ee3980ac73ae34fea6e4cbc18985
tar -xzf results/breaking-network28-20261113.tar.gz -C results
MPLBACKEND=Agg uv run --locked python scripts/audit_breaking_shards.py --network 28 \
  --input results/catalog-breaking-linux-28/shard-0 \
  --input results/catalog-breaking-linux-28/shard-1 \
  --input results/catalog-breaking-linux-28/shard-2 \
  --input results/catalog-breaking-linux-28/shard-3 \
  --input results/catalog-breaking-linux-28/shard-4 \
  --input results/catalog-breaking-linux-28/shard-5 \
  --input results/catalog-breaking-linux-28/shard-6 \
  --input results/catalog-breaking-linux-28/shard-7 \
  --input results/catalog-breaking-linux-28/shard-8 \
  --input results/catalog-breaking-linux-28/shard-9 \
  --input results/catalog-breaking-linux-28/shard-10 \
  --input results/catalog-breaking-linux-28/shard-11 \
  --input results/catalog-breaking-linux-28/shard-12 \
  --input results/catalog-breaking-linux-28/shard-13 \
  --input results/catalog-breaking-linux-28/shard-14 \
  --input results/catalog-breaking-linux-28/shard-15 \
  --output results/catalog-breaking-linux-28/audit.json
```

Every release member was verified against its source checksum after packaging.
`download.json` records the asset and complete member inventory. The originally
recorded audit paths identify the collection locations; rerunning the command
above records your own local paths while recomputing the same scientific results.
