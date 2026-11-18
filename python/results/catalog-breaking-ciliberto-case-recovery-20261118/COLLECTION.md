# Collect every fixed replacement and re-audit both complete cases

The [completed audit](COMPLETED_AUDIT.md) now passes both selected cases from all
215 branches and 860 trajectories. The instructions below describe the verified
collection and assembly procedure; the initial pending snapshot is retained as
a historical tooling check.

The [collection plan](collection-plan.json) binds all 18 replacement branches to
one immutable GitHub run, attempt, source revision and set of job IDs. Its scope
remains the original **215 branches and two selected cases**. The collector does
not integrate equations, dispatch workflows or choose a favorable subset.

## Verify downloaded evidence

Save complete GitHub API responses as `run.json`, `jobs.json` and `artifacts.json`
in a new snapshot directory. The endpoints are the selected run and its `jobs`
and `artifacts` resources; use `per_page=100`. These inventories fit on one page.
The collector rejects snapshots whose counts indicate omitted pages. Keep older
snapshots, especially the ones used for a published audit.

Download each original artifact ZIP as `artifact-ARTIFACT_ID.zip` in the archive
directory. The collector verifies its GitHub SHA-256, run, attempt, source,
selected job, name and creation time. It preserves the original ZIP separately
and rechecks every extracted byte on subsequent invocations. A failed job's
artifact is retained; job success alone is never numerical validation.

For each saved branch, the collector checks the original scientific fingerprint,
model and branch specification, requests, source hashes, package versions,
wrapper source and runtime provenance. It loads every available full trajectory,
checks its original times and observables, verifies reset execution evidence,
and independently recomputes all available pairwise comparisons. A consistent
numerical mismatch or explicit integration failure remains a failed result.
A killed or incomplete producer remains an incomplete inventory.

From `python/`:

```sh
uv run --locked --extra test --extra jaxkineticmodel python scripts/collect_ciliberto_evidence.py \
  --inputs results/catalog-breaking-ciliberto-case-recovery-20261118 \
  --selection results/catalog-breaking-ciliberto-case-recovery-20261118/collection-plan.json \
  --snapshots results/ciliberto-api-snapshot \
  --archives results/ciliberto-original-zips \
  --output results/ciliberto-collected
```

The actual initial API snapshot is preserved in [initial-api](initial-api), and
its [smoke result](initial-collection-status.json) reports all 18 jobs pending,
no collection errors and no case-recovery claim. To reproduce that pending-state
check, use `--snapshots results/catalog-breaking-ciliberto-case-recovery-20261118/initial-api`
and a new output directory. It needs no artifact downloads and performs no
numerical integrations. This is a collector check, not new scientific evidence.

## Assemble and audit the complete cases

After every selected replacement has a final producer record, rerun collection
with a current API snapshot and add:

```sh
  --preserved results/ciliberto-preserved-snapshot \
  --restored results/ciliberto-restored-import/restored-branch \
  --assemble results/ciliberto-reassembled
```

The assembly directory must be new. The tool checks and copies the surviving
snapshot against its preservation manifest, restores the exact published import,
and replaces **every one of the 18 predetermined branches**. All four requests
for each replacement come from its new calculation. A failed request cannot
reuse an older successful array. The original snapshot remains unchanged, the
original report is retained as `historical-report.json`, and separate provenance
records identify each replacement's original ZIP and record hashes.

The unchanged complete-case auditor then reads all 215 branches. It reconstructs
the original control inventory, recomputes every comparison and window summary,
and replays both conditional searches and controlled classifications. The new
assembled directory is retained only after this audit finishes. Its result may
report zero recovered cases; assembling complete outcomes does not make a
numerical failure pass. The separate full-model result is unchanged.

All **45 targeted tests** pass locally. They cover wrong attempts, tampered ZIP
extractions, changed final observations even after checksum updates, retained
mismatches and solver failures, incomplete checkpoints, and complete assembly
without fallback to older favorable data. Synthetic transport fixtures are not
experimental evidence; the existing full-array case-auditor tests run alongside
them.

The [full downloadable package](RELEASE.md) includes the unaffected arrays,
restored import, all replacement ZIPs, API snapshots and the complete-case audit.
Release notes record publication and fresh-download reproduction status.
The completed audit establishes two selected-case recoveries;
the initial pending-state smoke check makes no such claim.
