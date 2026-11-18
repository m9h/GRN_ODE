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

## Initial checkpoint result, 17 November 2026

The first full run ended with all 32 artifacts collected and verified, with no
missing artifacts or collection errors. `initial-checkpoint-summary.json` records
their run/job identities, original ZIP hashes, report hashes and saved array
hashes. The original ZIPs total 2,984,867,566 bytes. Collection reproduced all six
comparisons for each of 49 complete trajectories; all 294 comparisons pass,
including the full untreated baseline. In total, 274 of the required 5,236
integration arrays are complete and verified. The other saved arrays belong to
partially completed four-integration trajectories.

All 32 partition inventories remain incomplete. Six producers stopped cleanly
at a checkpoint; 26 were interrupted while an integration was running and retain
that earlier report status. These are execution limits, not completed negative
case results. No case has been recovered. The continuation
[run 44142019165](https://github.com/m9h/GRN_ODE/actions/runs/44142019165)
resumes every original partition from run 43925538098 using the unchanged
producer revision, protocols, tolerances and acceptance criteria. A completed
integration is reused only after its source, metadata, protocol and array bytes
have been verified. Work inside an interrupted integration must currently be
repeated; this makes the long Radau integrations a scheduling bottleneck.

## Continuation checkpoint, 18 November 2026

The first sixteen partitions of run 44142019165 have been collected through the
GitHub artifact connector and verified offline with the same collector. Their
original ZIP hashes, extracted bytes, source and protocol metadata, complete
arrays and completed comparisons all validate. The remaining sixteen partitions
are still pending in this dated snapshot; all 32 remain in the fixed selection.

`continuation-progress-20261118.json` compares each collected partition with its
first-pass parent artifact and verifies the recorded resume lineage. All 137
previously complete arrays in these sixteen partitions remain byte-identical.
They now contain 274 complete arrays, an addition of 137. Their 58 completed
four-integration trajectories pass all 348 pairwise comparisons. These counts
describe only the collected continuation partitions; they are not a union chosen
from passing trajectories across runs. No partition is complete, and no selected
case or whole model has been promoted.
