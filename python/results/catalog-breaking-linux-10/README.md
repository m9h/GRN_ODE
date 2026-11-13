# Complete network 10 breaking search

All 112 initial cases were evaluated; 112 pass
numerical validation. The audit reconstructs 2045 conditional
trials, 4741 response-trials and 8443
branch records (8158 distinct specifications).
There are 0 unresolved conditional decisions.
Numerical validation is separate from whether a case exhibits a resolved memory effect.

Workflow: [43374603951](https://github.com/m9h/GRN_ODE/actions/runs/43374603951).
`source-artifacts.json` preserves producer revisions, artifact digests and file hashes.
Every partition retains its own shared controls. Reports and the combined audit
are tracked in Git; the release contains the referenced compressed evidence and
any parent-resume metadata. It excludes hidden restart-cache duplicates.

These archives contain recorded pointwise comparisons and window summaries,
not full raw trajectory arrays. The independent audit verifies every record,
reconstructs the conditional search and recomputes scores without reintegration.

From `python/`, with the producer revisions available in local Git history:

```bash
gh release download kinetics-hoefnagel-20261113 --repo m9h/GRN_ODE \
  --pattern breaking-network10-20261113.tar.gz --dir results
shasum -a 256 results/breaking-network10-20261113.tar.gz
# Expected: dd4464170e49f71e5553c0d66c1c14b0a2293ee44f5540c619938b5ceffb3af4
tar -xzf results/breaking-network10-20261113.tar.gz -C results
MPLBACKEND=Agg uv run --locked python scripts/audit_breaking_shards.py --network 10 \
  --input results/catalog-breaking-linux-10/shard-0 \
  --input results/catalog-breaking-linux-10/shard-1 \
  --input results/catalog-breaking-linux-10/shard-2 \
  --input results/catalog-breaking-linux-10/shard-3 \
  --input results/catalog-breaking-linux-10/shard-4 \
  --input results/catalog-breaking-linux-10/shard-5 \
  --input results/catalog-breaking-linux-10/shard-6 \
  --input results/catalog-breaking-linux-10/shard-7 \
  --input results/catalog-breaking-linux-10/shard-8 \
  --input results/catalog-breaking-linux-10/shard-9 \
  --input results/catalog-breaking-linux-10/shard-10 \
  --input results/catalog-breaking-linux-10/shard-11 \
  --input results/catalog-breaking-linux-10/shard-12 \
  --input results/catalog-breaking-linux-10/shard-13 \
  --input results/catalog-breaking-linux-10/shard-14 \
  --input results/catalog-breaking-linux-10/shard-15 \
  --output results/catalog-breaking-linux-10/audit.json
```

Every release member was verified against its source checksum after packaging.
`download.json` records the asset and complete member inventory. The originally
recorded audit paths identify the collection locations; rerunning the command
above records your own local paths while recomputing the same scientific results.
