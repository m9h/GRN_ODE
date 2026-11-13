# Two completed Vilar precision branches

The resumed Linux run completed the **paired-normal** and **paired-sham** arms
of `DA__up--DR__up`. Each trajectory covers the complete original 300-unit
protocol and all 30,001 observation times. The independent array audit passes
all three comparisons per branch: Taylor 128 versus Taylor 192, and both
Taylor trajectories versus RoadRunner, at the unchanged acceptance thresholds.

These two arms belong to a case already recovered by the SciPy/RoadRunner
audit. They add evidence for precision convergence and checkpoint resumption;
they add **no new validated cases**. The Vilar paired result remains **139/142**.
The three unresolved cases require the separate
[23-control plan](../catalog-paired-taylor-vilar-controls-20261113/README.md)
and nine branches from the ongoing failed-branch batch.

`audit.json` recomputes comparisons from every saved array. Its missing
partition inventory remains explicit. `sources.json` binds the original
GitHub artifacts, producer revision, branch identities, source reports and
release checksums. The per-partition metadata records the original integration
requests, runtime, reset counts and checkpoint restoration. It is not a
substitute for the full arrays.

The [release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-vilar-precision-20261113)
preserves both original artifact ZIPs byte for byte, including all six full
trajectory arrays and exact precision checkpoints. This keeps the evidence
available after GitHub's temporary action artifacts expire.

| Partition | Arm | ZIP SHA-256 |
| --- | --- | --- |
| 2 | paired normal | `efc48f69328aaa7b368fcd32d756a2ecd305c56279abf4806c094de491980aa3` |
| 4 | paired sham | `0e955f454cc6bf15b6ec7d9fd818424e6dff2362755f4df4c6ace1fa676c86b6` |

Extract each ZIP into its own directory. From `python/`, independently repeat
the saved-array audit with the uv project environment; Heyoka is not needed:

```bash
uv run --locked python scripts/audit_taylor_partitions.py \
  --input /path/to/partition-2/evidence \
  --input /path/to/partition-4/evidence \
  --allow-partial --output /tmp/vilar-precision-audit.json
```

Expected: two full-protocol branches, both precision-converged and agreeing
with RoadRunner, with incomplete original-failure coverage and no claim of
complete case recovery. The numerical producer is
`ec8ec7cbadecd2a8c2067992011c88028eb5690f` in
[run 43483480217](https://github.com/m9h/GRN_ODE/actions/runs/43483480217).
