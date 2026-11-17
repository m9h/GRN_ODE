# Collecting the complete Fuss case-control experiment

`collection-selection.json` fixes all 32 original partition indices, GitHub run
43925538098, attempt 1, the producing revision and each actual job ID. It was
captured before examining checkpoint results. Continuations require a new,
explicit selection; passing branches cannot be selected from different runs.

The read-only collector can collect a completed matrix job while other jobs in
the same workflow are still running. It performs no integrations or workflow
dispatches. From `python/`, using the matching locked environment:

```sh
uv run python scripts/collect_scipy_case_partitions.py \
  --selection results/catalog-breaking-fuss-full-case-plan-20261116/collection-selection.json \
  --inputs results/catalog-breaking-fuss-full-case-plan-20261116 \
  --output results/fuss-case-collection --watch
```

Each original ZIP is retained separately by run, attempt and artifact ID. The
collector verifies its server SHA-256, extracted file bytes, producing Git
revision, input evidence, complete original branch selection, metadata, reset
protocols and every saved complete array. Completed branch comparisons are
recomputed from the arrays. Linux evidence can be audited on another platform;
the producer's recorded environment remains part of the experiment fingerprint.

While watching, verified files are cached only within that process, with file
identity and change checks. Restarting verifies ZIP and extracted bytes again.
Source or integrity failures stop collection. Transport retries preserve the
same selected artifact. When every selected job is terminal, the collector exits
and reports indices needing continuation, rather than polling a terminal run
indefinitely. Exit 1 means the selected executions ended with incomplete
inventories or missing artifacts; exit 2 denotes verification failure.

A checkpointed job may have a GitHub failure conclusion because its time budget
ended. This is distinct from a numerical mismatch. `status.json` preserves both
statuses, completed integration counts and reported timings. A branch whose
four integrations agree still cannot recover a case by itself. Only when all
32 original partitions and all 1,309 trajectories are complete does the separate
case auditor replay all 18 selected cases and their controls into `audit.json`.
The 314 previously passing cases are outside this recovery experiment, so its
output alone cannot establish whole-model recovery.
