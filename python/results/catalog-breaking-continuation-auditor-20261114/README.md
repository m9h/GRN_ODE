# Full-model audits across targeted continuations

`scripts/audit_breaking_continuations.py` assembles a predetermined complete
partition selection from existing collectors. Each selection binds its run,
attempt, job and source revision. The tool checks every extracted file against
the artifact ZIP, then calls the existing complete-model auditor without
combining branch records from different partitions. It performs no numerical
integration and never chooses individual favorable cases or branches.

Validation through uv passes 46 tests covering the new assembly, collection,
partitioning and scientific evidence audit. Tests include a complete 22-case
model spread over two simulated run identities; partial or duplicate plans;
wrong jobs and revisions; timeouts; missing artifacts; altered ZIPs and extracted
files; and rejection of unavailable or changed source provenance. The CI fixture
supplies its recorded source hashes so it works in shallow checkouts. Production
code still checks the historical Git objects.

The separate real-artifact smoke check uses all four original network-27
artifacts from run 43101294718. It checks actual Git objects and all 348
extracted files against the four original ZIPs. The resulting audit reproduces
22/22 passing cases, 57 conditional trials, 301 partition-local branch records
and 260 distinct branch specifications. `smoke-plan.json` and
`smoke-verification.json` preserve exact job identities, ZIP hashes and the
verification results. This repeats an existing result; it adds no model or case
to the scientific coverage counts.

For a collected original run, from `python/`:

```bash
uv run --locked python scripts/audit_breaking_continuations.py \
  --plan results/catalog-breaking-continuation-auditor-20261114/smoke-plan.json \
  --collection-root /path/to/collected-artifacts --output /tmp/fresh-combined-smoke
```

The live plans are:

- [Tyson network 5](../catalog-breaking-network5-targeted-continuation-20261114/combined-audit-plan.json):
  indices 13 and 15 from their continuations, the other fourteen from run
  43485099563; all 58 initial cases remain required.
- [Vilar network 32](../catalog-breaking-network32-resume-repair-20261114/combined-audit-plan.json):
  index 7 from its repair, the other fifteen from run 43485109761; all 204
  initial cases remain required.

Pass the relevant collector roots as repeated `--collection-root` arguments.
`--watch` waits for the chosen artifacts and exits after a complete audit, an
audit error, or evidence that a selected partition needs another continuation.
Use a fresh output directory for a changed plan. `plan_sha256` in the output is
the canonical JSON fingerprint, independent of whitespace in the plan file.

Artifact integrity and reproduced window-based classifications do not create
raw trajectory evidence absent from the original producer. Those numerical
limitations remain explicit in the model audit and separate solver diagnostics.
