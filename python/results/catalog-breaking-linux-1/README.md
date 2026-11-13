# Complete network 1 breaking validation

All 528 initial cases in the Edelstein 1996 acetylcholine-receptor model pass
independent numerical validation. Sixteen Linux partitions retain 9,452 conditional
trials, 30,169 response-trials and 38,024 branch records (37,570 distinct branch
specifications), with no unresolved continuation decisions. All eight controls
and each required observation remain present. Passing numerical validation does
not mean that every case exhibits a resolved history-dependent response.

Producer revision: `e5ff9bb131b3a815feb584793b9f68dda53ce7a7`.
Workflow: [43273682876](https://github.com/m9h/GRN_ODE/actions/runs/43273682876).
`source-artifacts.json` retains artifact and copied-file hashes. Each partition's
independent evidence remains in its own directory; duplicate shared controls
are not overwritten.

The 403 compressed branch/case archives are in the
[network-1 release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-network1-20261113).
They contain recorded pointwise comparisons and window summaries, not full raw
trajectory arrays or hidden restart checkpoints. Reports and the combined audit
are tracked in Git. `download.json` records the asset and every member's hash.

From `python/`:

```bash
gh release download kinetics-network1-20261113 --repo m9h/GRN_ODE \
  --pattern breaking-network1-20261113.tar.gz --dir results
shasum -a 256 results/breaking-network1-20261113.tar.gz
# Expected: ad1a8c6a2aa500961519fa9d919c5330bdbf2864ae15d3a2a1066f29138e87dc
tar -xzf results/breaking-network1-20261113.tar.gz -C results
MPLBACKEND=Agg uv run --locked python scripts/audit_breaking_shards.py --network 1 \
  --input results/catalog-breaking-linux-1/shard-0 \
  --input results/catalog-breaking-linux-1/shard-1 \
  --input results/catalog-breaking-linux-1/shard-2 \
  --input results/catalog-breaking-linux-1/shard-3 \
  --input results/catalog-breaking-linux-1/shard-4 \
  --input results/catalog-breaking-linux-1/shard-5 \
  --input results/catalog-breaking-linux-1/shard-6 \
  --input results/catalog-breaking-linux-1/shard-7 \
  --input results/catalog-breaking-linux-1/shard-8 \
  --input results/catalog-breaking-linux-1/shard-9 \
  --input results/catalog-breaking-linux-1/shard-10 \
  --input results/catalog-breaking-linux-1/shard-11 \
  --input results/catalog-breaking-linux-1/shard-12 \
  --input results/catalog-breaking-linux-1/shard-13 \
  --input results/catalog-breaking-linux-1/shard-14 \
  --input results/catalog-breaking-linux-1/shard-15 \
  --output results/catalog-breaking-linux-1/audit.json
```

The producer revision must be available in local Git history. This audit
verifies all archived records, reconstructs the conditional search and
recomputes the scores; it does not rerun numerical integration.
