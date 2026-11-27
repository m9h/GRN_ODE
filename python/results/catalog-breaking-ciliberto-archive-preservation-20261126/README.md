# Bounded storage for the complete Ciliberto audit

The refreshed 27 November 2026 snapshot contains **198 original ZIPs totaling
486,059,082,836 bytes**. The previous 177-archive plan is retained verbatim in
`prior-plan.json`; validation requires every earlier artifact identity and the
complete original partition selection to remain unchanged. Downloading and
extracting every archive into the persistent local cache cannot fit. These
scripts change transport and cache lifetime; the models, solvers, environments,
requests, grids, numerical comparisons, and case scoring remain unchanged.

The complete scientific selection is still **256 partitions / 6,859 later
controls / 7,334 total branches / 74 cases**. The snapshot explicitly retains 57
pending partitions and partition 43's missing artifact. GitHub reports that its
runner lost communication and its upload step was skipped. That is missing
evidence, not a numerical failure result.

## Preservation

`preserve_ciliberto_archives.py check` validates the pinned original selection,
all API snapshots, actual jobs, archive metadata, and the complete scientific
scope with the existing frozen collectors. The new workflow's `partitions`
input selects archive transfers only. Its default `[0]` is a transport pilot;
it cannot reduce the scientific selection or produce a case pass.

Partition 0 already has an accepted cloud preservation job. Partition 194 has
a separate local transfer pilot using the same transport code. Check their
current receipts before selecting a new transfer batch; omit archives already
preserved or covered by an accepted pending job. Capturing 198 archive records
does not mean those archives have been preserved or scientifically audited.

Each cloud job downloads one original artifact and verifies its exact size and
SHA-256. `archive_release_chunks.py` publishes it in 500 MiB pieces, checks
GitHub's asset digests, downloads each piece again, and reproduces the original
ZIP checksum before publishing the manifest. Releases are grouped by 32 original
partitions. Existing assets must match exactly and are never overwritten.
This stays below GitHub's [2 GiB per-asset and 1,000 assets per-release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).
The original ZIP is never recompressed or edited.

A failed upload leaves the original and any published pieces intact. A fresh
courier working directory can reuse matching pieces and repeat verification.
An ambiguous dispatch or upload response requires inspecting the existing run
or asset before retrying. Partial pieces without a complete manifest do not
constitute a preserved archive. Workflow success is transport evidence only.

## Streaming scientific verification

The full-case auditor still accepts the original cached evidence descriptor.
Its optional release provider reconstructs one ZIP in a private temporary
directory, verifies the original SHA-256 and exact extracted file inventory, and
calls the same `verify_partition` and numerical audit functions as before. It
writes checked branch windows and provenance into the durable audit output,
then removes only the generated local cache. The verified release pieces,
original local files, API snapshots, and prior audits are retained.

The default scratch budget is **16 GiB**, checked both before download and against
the ZIP's expanded size before extraction. No complete-case claim is possible
until every required branch is present and checked. Missing manifests, failed
downloads, mismatched hashes, truncated arrays, and pending jobs remain explicit
errors or incomplete work. A cache path in a streamed branch record identifies
its temporary verification location; the partition's `archive_preservation`
record supplies the lasting release IDs, manifest hash, and original ZIP hash.

Build an archive index from the courier's verified `receipt.json` files:

```json
{"controls": {"14517099024": {"release_id": 123, "release_tag": "...",
  "manifest_asset_id": 456, "manifest_sha256": "...", "manifest_bytes": 1234,
  "artifact_id": 14517099024, "archive_sha256": "sha256:...",
  "archive_bytes": 2480718537, "fresh_download_verified": true}}}
```

Those numbers are illustrative except the original artifact ID and size. Use
the actual published receipt verbatim. Declare every available artifact for
each streamed stage; a missing entry is a verification error. An omitted stage
uses the existing cache. The archive index itself is pinned by SHA-256 throughout
the audit. Published branch evidence remains a separately declared input.

```sh
uv run --locked --extra test --extra jaxkineticmodel \
  python scripts/audit_ciliberto_full_cases.py audit \
  --inputs /path/to/pinned-original-inputs \
  --sources /path/to/full-sources.json --output /path/to/new-audit \
  --archive-index /path/to/archive-index.json \
  --archive-scratch /path/to/scratch --archive-budget-gib 16
```

Tests exercise byte-exact reconstruction, resumable publication without
overwriting, missing/corrupt/reordered chunks, mismatched source identities,
storage limits, temporary cache cleanup after success or failure, and streamed
versus cached branch/window audit equivalence. Existing full-case tests retain
the 7,334-branch completeness and unchanged case-replay checks. The courier
validation gate runs both sets. No numerical integration runs in these tests
or in the preservation workflow.
