# Complete network 12 breaking search

All 216 initial cases were evaluated; 216 pass
numerical validation. The audit reconstructs 3323 conditional
trials, 7830 response-trials and 13588
branch records (13230 distinct specifications).
There are 0 unresolved conditional decisions.
Numerical validation is separate from whether a case exhibits a resolved memory effect.

Workflow: [43370464101](https://github.com/m9h/GRN_ODE/actions/runs/43370464101).
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
  --pattern breaking-network12-20261113.tar.gz --dir results
shasum -a 256 results/breaking-network12-20261113.tar.gz
# Expected: 5992e060d3a059b9043bf20b9d0f77c48248404a712b121f0d2fde5d42a9a2c7
tar -xzf results/breaking-network12-20261113.tar.gz -C results
MPLBACKEND=Agg uv run --locked python scripts/audit_breaking_shards.py --network 12 \
  --input results/catalog-breaking-linux-12/shard-0 \
  --input results/catalog-breaking-linux-12/shard-1 \
  --input results/catalog-breaking-linux-12/shard-2 \
  --input results/catalog-breaking-linux-12/shard-3 \
  --input results/catalog-breaking-linux-12/shard-4 \
  --input results/catalog-breaking-linux-12/shard-5 \
  --input results/catalog-breaking-linux-12/shard-6 \
  --input results/catalog-breaking-linux-12/shard-7 \
  --input results/catalog-breaking-linux-12/shard-8 \
  --input results/catalog-breaking-linux-12/shard-9 \
  --input results/catalog-breaking-linux-12/shard-10 \
  --input results/catalog-breaking-linux-12/shard-11 \
  --input results/catalog-breaking-linux-12/shard-12 \
  --input results/catalog-breaking-linux-12/shard-13 \
  --input results/catalog-breaking-linux-12/shard-14 \
  --input results/catalog-breaking-linux-12/shard-15 \
  --output results/catalog-breaking-linux-12/audit.json
```

Every release member was verified against its source checksum after packaging.
`download.json` records the asset and complete member inventory. The originally
recorded audit paths identify the collection locations; rerunning the command
above records your own local paths while recomputing the same scientific results.
