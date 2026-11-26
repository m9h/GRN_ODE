# Continue unfinished Rohwer later controls

The Rohwer phosphotransferase model (network 35, BIOMD0000000038) has a
fixed 123-case memory-breaking investigation. Its complete plan requires
11,674 diagnostic/control branches: 750 first-stage branches and 10,924 later
controls, with the latter distributed across 512 original partitions. These
controls distinguish a changed response to the conditioning history from the
response to an isolated stimulus at the same time. Completion still requires
every planned branch and the original full-case replay; the number of files or
successful jobs cannot establish a recovered case.

The authenticated 26 November parent audit contains 232 original archives and
6,279 independently checked trajectories. Partition 5 has complete diagnostics,
including its mismatch, and is retained unchanged. The other 231 available
partitions need continuation. Partition 23 has a separate missing-output
recovery, and 279 partitions remain assigned to their existing original jobs.
All 512 selections remain in this binding. Among the 232 available outputs,
1,432 terminal diagnostics, 231 resumable diagnostics and 3,328 unstarted
diagnostics are accounted for explicitly.

## What changes

Only orchestration and evidence routing change. The original numerical
implementation, SBML, time grids, requests, solver parameters, package versions
and dependency sources remain frozen. `continue_rohwer_later.py` restores an
original ZIP only after verifying its producer identity, checksum, complete
file inventory and independent array audit. It copies the earlier execution
record and mutable branch metadata into `lineage/` before continuing.

Completed diagnostics, including numerical failures and mismatches, are never
recomputed. Completed requests within an interrupted branch retain exactly the
same arrays and metadata. The unchanged numerical kernel is called with
`resume=True`. Unstarted branches are scheduled before the interrupted branches
so that one slow request cannot repeatedly prevent untouched controls from
running. The original 19,200-second computation budget remains unchanged.

The original kernel records an unsuccessful prior request in
`previous_incomplete_attempts` when it resumes that request. The old collectors
intentionally reject that field and remain unchanged. The new adapter checks
each history entry against the checksum-bound parent record, then constructs a
temporary audit view omitting only that separately checked field and updating
the report's record checksum. It runs the unchanged full-array validator on
that view. All numerical fields, source identities and array bytes are
identical. The proof retains the actual and temporary record/report hashes;
original evidence is never rewritten. Saved continuation receipts must reproduce
this independent audit, including the preserved failure history.

## Bounded submissions, complete scope

The workflow accepts one to four sorted, unique eligible indices per dispatch.
This avoids placing 231 long jobs into a queue at once: earlier workflows have
already experienced 24-hour runner-queue expiry. Batching changes submission
timing, not the required work. Every binding retains all 512 original selections,
all 231 eligible continuations and an explicit list of eligible indices outside
that run. The first planned batch is `[0,1,2,44]`, including the real interrupted
branch with an earlier failed request in partition 44.

Never resubmit an accepted dispatch just because its validation or computation
jobs are queued. Capture its actual run ID and complete job pages after the
validation gate passes. Bind that exact batch with:

```sh
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/collect_rohwer_later_continuation.py \
  --run captured-run.json --jobs complete-jobs.json \
  --revision EXACT_SOURCE_SHA --indices '[0,1,2,44]' \
  --output actual-job-binding.json
```

Each collection descriptor names the binding, an API snapshot directory
containing `run.json`, `jobs.json`, and complete `artifacts.json`, and a cache
with the original downloaded ZIP and verified extracted payload. The full-case
auditor accepts repeated `--controls-continuation descriptor.json` options to
combine disjoint batches. It rejects overlapping selections. Both complete
original batch snapshots remain mandatory, and the separate partition-23
recovery can be supplied with `--controls-recovery`.

A queued/running continuation, or a terminal job without an artifact, retains
its already audited parent evidence. A terminal uploaded result replaces that
parent only after source, archive, lineage and full-array checks pass. A corrupt
replacement produces a verification error; it never silently falls back to an
old result. Source API snapshots and per-batch provenance are preserved with
each new full-case audit. No case is replayed until every one of the 11,674
required branch outcomes is available and verified.

This first continuation generation may itself end with incomplete requests.
Those outputs must be audited and bound explicitly before another generation;
the original parent files and this generation's complete scope remain evidence.
Additional original partitions will need their own audited continuation
bindings if their currently pending jobs finish with partial results.

## Validation and scientific limits

The tests exercise immutable complete requests, failed-attempt history,
timeouts, false completion, bounded job identities, independent array checks,
pending-parent retention, corrupt replacements, disjoint batch collection and
the complete 11,674-branch/123-case gate. Synthetic arrays are test fixtures,
not evidence of numerical convergence. Separate offline checks restore actual
partitions 0, 1, 2 and 44 from original archives and reproduce their prior branch
audits; no numerical solver runs during those checks. The Linux workflow must
also verify the complete released inputs and installed frozen dependencies
before computation can start.

The binding does **not** claim any newly completed trajectory, recovered case or
passing whole-model audit. The independent outcomes of future computations,
including any persistent failures, remain to be collected and interpreted.
