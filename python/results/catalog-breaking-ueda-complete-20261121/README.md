# Ueda: all 302 breaking cases validated

The Ueda circadian-clock model (`BIOMD0000000022`, network 11) now has a
combined **302/302 passing case inventory**. A fresh audit of the published
original evidence reproduces 298 passing cases and four numerical failures.
Full independent control trajectories recover those exact four failures.
The original failed results remain preserved.

| Originally failing case | Complete-control audit | Conditional paths |
|---|---|---|
| `CCn__down--CCc__up` | Pass | Primary and refined searches match |
| `CCn__down--Clkc__up` | Pass | Primary and refined searches match |
| `Perm__down--Perc__up` | Pass | Primary and refined searches match |
| `Timm__down--Timc__up` | Pass | Primary and refined searches match |

The recovery covers **323 distinct branch specifications, 1,292 complete
trajectories and 1,938 passing pairwise comparisons**. Each branch uses two
RoadRunner requests and two SciPy Radau requests. Every saved observation,
observable, reset and required control is checked. The largest scaled error is
0.78004, below the unchanged acceptance threshold of 1. The full untreated
baseline passes, and no previously passing branch is flagged for revalidation.

This establishes numerical agreement for the specified history-dependent
response protocols. The learning interpretation still depends on their matched
controls and operational definitions; it is not a separate test of the
philosophical thesis of *Ingressing Minds*.

## Evidence and scope

- [Combined model audit](combined-model-audit.json): all 302 case identities,
  their original statuses, and the provenance of each passing result.
- [Complete recovery audit](selected-case-audit.json): all 323 branch records,
  array hashes, full comparisons and four conditional case replays.
- [Freshly reproduced original audit](original-model-audit.json) and
  [original report](original-model-report.json): 13,315 branch records,
  3,354 conditional trials and the unchanged 298/302 result.
- [Collection proof](collection-summary.json): all 32 original ZIP identities,
  sizes and server checksums, exact source revisions, and report checksums.
- [Fixed selection](selection.json) and [API snapshots](api/): every job and
  branch was retained from the original plan.

[Run 44393623529](https://github.com/m9h/GRN_ODE/actions/runs/44393623529)
completed all 32 fixed partitions at producer revision
`b585ee97de7000c2ec1afe5454216629601eee87`. Its 153 new branches were combined
with 156 complete preserved branches and 24 published imports, ten of which
overlap the preserved set. The result contains exactly 323 unique branches.
Collection and complete-array auditing used unchanged revision
`0c3c315dd34391abd4c38bfe93a358e78779451e`.

The original whole-model audit was reproduced from a fresh download of
[`kinetics-ueda-diagnostics-20261113`](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-ueda-diagnostics-20261113).
Its archive SHA-256 is
`d8c4cc37037e2afd5cbcf093e4313cf0677e34021edb06d90e160fdaec07147f`.
The exact original report is bound by SHA-256
`26b75b6a08bed830f9e10acc3fb04d647b7cc81df5d46a0e145c42b5a8d1d258`.

**Raw-evidence publication remains pending.** All 32 new original ZIPs
(9,781,886,357 bytes), their extracted arrays, the preserved inputs and the
assembled evidence are retained locally. They are not included in this Git
directory. The pinned Actions artifacts remain downloadable until their
recorded expiry dates. A durable release of the new raw evidence is still
required; the JSON reports alone are not the complete reproducibility package.

## Reproduce the verification

Use the unchanged [collection and assembly guide](../catalog-breaking-ueda-continuation-20261118/COLLECTION.md)
with the selection and API snapshots here. Keep every original ZIP as
`artifact-ID.zip`, checking its size and digest against `collection-summary.json`.
Use the preserved inputs and restored imports from the
[preservation release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-ueda-preservation-20261118).
The collection command must finish with all 32 partitions, then assemble all
323 branches and run the full case auditor. It must report four recovered
cases, a passing baseline and no previously passing branches requiring revalidation.

Reproduce the original 302-case audit separately using the instructions in the
[original report](https://github.com/m9h/GRN_ODE/blob/e891478b94fb732a3c4bd2e799eb7af35ace6f2a/python/results/catalog-breaking-ueda11-local/README.md).
The original release provides the compressed evidence; copy the original
report from Git into the extracted directory before running that audit.

The [combination check](combine_model_audits.py) reads an evidence directory
containing `assembled/`, `collection/`, and `original-model/`. The last directory
must contain the original `BIOMD0000000022.json` and the freshly generated
`reproduced-audit.json`. Copy the checker to that evidence directory and run it
with Python. It rejects missing or extra recovered cases, changed source-report
identity, incomplete arrays, failing comparisons, unresolved original searches,
changed conditional paths and contradictory previously passing branches. It
adds the four recoveries to the original 298 passes and writes a new combined
audit without overwriting an existing result.

No numerical integrations were performed during these collection, replay and
accounting steps. The frozen numerical producers, simulator settings, grids,
controls and acceptance thresholds are unchanged.
