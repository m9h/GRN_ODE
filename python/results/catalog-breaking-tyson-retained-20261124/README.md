# Retained Tyson1991 evidence: partitions 14 and 15

These two original GitHub artifact ZIPs preserve the completed partitions that
remain available for the full 58-case Tyson1991 inventory (BioModel 5, network 5).
They contain eight recorded cases: seven pass the original numerical audit and
one retains a failure. This is not a whole-model completion claim.

| Partition | Original run | Original artifact | Cases | Passing cases |
|---|---|---|---|---|
| 14 | [44930974577](https://github.com/m9h/GRN_ODE/actions/runs/44930974577) | 14722269591 | 4 | 3 |
| 15 | [44118517338](https://github.com/m9h/GRN_ODE/actions/runs/44118517338) | 14349101938 | 4 | 4 |

Both use frozen producer `cae38e9a6ec4c7567ea6cbf2908778f409a1ebb0`.
The original ZIP bytes are unchanged; the manifest records their SHA-256,
sizes, producer/job identities, selected cases and every extracted file hash.
The ZIPs contain saved branch comparisons and response-window summaries.
They do **not** contain the complete raw trajectory arrays, so they cannot
support a fresh pointwise comparison of trajectories beyond the saved evidence.

The final partition-14 continuation finished the last previously pending case.
Its 121 branch records include 120 passes and one failure; all 114 earlier
passing records were retained byte-for-byte. However, the full-model audit
then found the historical payloads for partitions 0–13 unavailable: the older
GitHub artifacts had expired and their temporary local payloads were absent.
Historical collection metadata remains preserved, but missing bytes are not
represented as available originals.

All fourteen missing partitions have now been submitted for recomputation with
the unchanged numerical source, model, reference data and dependency lock.
`replacement-selection.json` binds the complete sixteen-partition inventory,
including these two retained partitions. The original partition-0 submission
appeared late; a queued duplicate was cancelled, and the original job is the
one selected. No whole-model validation increase is claimed before the new
full inventory is collected and audited.

## Verify the preserved files

Download the release and run the standalone standard-library verifier:

```sh
gh release download kinetics-tyson-retained-20261124 --repo m9h/GRN_ODE --dir tyson-retained
python3 tyson-retained/verify.py --assets tyson-retained
```

The verifier pins the manifest checksum and checks both original ZIPs and all
230 payload files. It performs no integrations. `SHA256SUMS` also covers the
documentation, verifier and complete replacement selection. This integrity
check is separate from the scientific full-model audit, which remains pending.
