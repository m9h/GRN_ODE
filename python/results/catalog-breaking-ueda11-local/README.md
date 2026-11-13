# Complete local Ueda search and Linux comparison

The original macOS worker finished all 302 Ueda cases with 298 passing. The
complete evidence audit records 3,354 conditional trials, 5,363 response-trials
and 13,315 distinct branches. All integrations finish; 24 branch mismatches
affect four cases. No conditional decisions remain unresolved.

`run-comparison.json` audits both the local run and the complete sixteen-partition
Linux run before comparing them. All 302 case paths agree. There are no trials
unique to either run, and all 10,726 shared response/engine assessments have
matching raw and controlled labels. Both runs retain the same four failed
cases. Matching labels do not establish agreement between complete trajectories.

The original local producer is `70a3afad61357e94873ff62a7300c099b4c7ae3e`.
Reports, audits and source metadata are tracked in Git. The release archive
contains all 138 referenced compressed evidence files, each read back and
checked against its source hash after packaging. These files preserve recorded
pointwise comparisons and window summaries, not full raw trajectory arrays.

From `python/`, download the original evidence and reproduce its audit:

```bash
gh release download kinetics-ueda-diagnostics-20261113 --repo m9h/GRN_ODE \
  --pattern breaking-network11-local-20261113.tar.gz --dir results
shasum -a 256 results/breaking-network11-local-20261113.tar.gz
# Expected: d8c4cc37037e2afd5cbcf093e4313cf0677e34021edb06d90e160fdaec07147f
tar -xzf results/breaking-network11-local-20261113.tar.gz -C results
MPLBACKEND=Agg uv run --locked python scripts/audit_breaking_catalog.py \
  --input results/catalog-breaking-ueda11-local --network 11 \
  --source-revision 70a3afad61357e94873ff62a7300c099b4c7ae3e \
  --output results/catalog-breaking-ueda11-local/audit.json
```

For the comparison, also follow the [Linux evidence download instructions](../catalog-breaking-linux-11/README.md).
The following command audits both inventories before comparing every case:

```bash
uv run --locked python - <<'PY'
from pathlib import Path
from grn_memory.catalog_memory import write_json
from scripts.compare_breaking_runs import compare
result = compare(Path('results/catalog-breaking-ueda11-local'),
    [Path('results/catalog-breaking-linux-11') / f'shard-{i}' for i in range(16)],
    11, '70a3afad61357e94873ff62a7300c099b4c7ae3e')
write_json(Path('results/catalog-breaking-ueda11-local/run-comparison.json'), result)
print(result['totals'])
PY
```

The audits check saved records without reintegrating. Local paths recorded by
the original audits are provenance; a reproduction records its own paths.
