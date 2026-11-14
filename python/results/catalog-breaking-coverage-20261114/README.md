# All 35 models: breaking-screen evidence coverage

This index reconciles the committed complete-model audits against the original 35-model catalog and its unchanged candidate calibrations. It records **28 models with complete initial-case inventories**, **23 with a passing whole-model audit**, **five terminal models retaining failures**, and **seven unfinished models**. It is an index of existing evidence, not a new numerical audit.

Four of the 23 passing models (networks 6, 14, 17 and 33) have **zero eligible breaking cases** under the declared candidate selection. Their validated controls and empty candidate inventories do not demonstrate a learning response. Completion of initial cases also does not imply that every conditional path or numerical check passed.

`index.json` preserves every indexed complete-model audit, including failed originals alongside subsequent recoveries. Its model status requires a whole-model passing audit; it never combines favorable individual branches or case counts. The completed Ueda and Ciliberto branch diagnostics are explicitly excluded from model-recovery counts. Every source audit and calibration has a recorded SHA-256.

| Network | BioModels ID | Planned cases | Status | Evidence |
| --- | --- | ---: | --- | --- |
| 1 | BIOMD0000000001 | 528 | Validated | [Audit](../catalog-breaking-linux-1/audit.json) |
| 2 | BIOMD0000000002 | 624 | Unfinished | Awaiting complete audit |
| 3 | BIOMD0000000003 | 8 | Initial cases complete; validation fails | [Audit](../catalog-breaking-original-completed/audit.json) |
| 4 | BIOMD0000000004 | 54 | Validated | [Audit](../catalog-breaking-goldbeter4-full-recovery/audit.json) (other runs retained in index) |
| 5 | BIOMD0000000005 | 58 | Unfinished | Awaiting complete audit |
| 6 | BIOMD0000000006 | 0 | Validated; no eligible cases | [Audit](../catalog-breaking-original-completed/audit.json) |
| 7 | BIOMD0000000010 | 220 | Validated | [Audit](../catalog-breaking-original-completed/audit.json) |
| 8 | BIOMD0000000069 | 332 | Initial cases complete; validation fails | [Audit](../catalog-breaking-original-completed-20261112/audit.json) |
| 9 | BIOMD0000000016 | 66 | Validated | [Audit](../catalog-breaking-original-completed/audit.json) |
| 10 | BIOMD0000000017 | 112 | Validated | [Audit](../catalog-breaking-linux-10/audit.json) |
| 11 | BIOMD0000000022 | 302 | Initial cases complete; validation fails | [Audit](../catalog-breaking-linux-11/audit.json) (other runs retained in index) |
| 12 | BIOMD0000000021 | 216 | Validated | [Audit](../catalog-breaking-linux-12/audit.json) (other runs retained in index) |
| 13 | BIOMD0000000023 | 78 | Validated | [Audit](../catalog-breaking-original-completed/audit.json) |
| 14 | BIOMD0000000024 | 0 | Validated; no eligible cases | [Audit](../catalog-breaking-original-completed/audit.json) |
| 15 | BIOMD0000000026 | 398 | Unfinished | Awaiting complete audit |
| 16 | BIOMD0000000027 | 8 | Validated | [Audit](../catalog-breaking-original-completed/audit.json) |
| 17 | BIOMD0000000483 | 0 | Validated; no eligible cases | [Audit](../catalog-breaking-original-completed/audit.json) |
| 18 | BIOMD0000000029 | 40 | Validated | [Audit](../catalog-breaking-original-completed/audit.json) |
| 19 | BIOMD0000000031 | 14 | Validated | [Audit](../catalog-breaking-original-completed/audit.json) |
| 20 | BIOMD0000000631 | 484 | Validated | [Audit](../catalog-breaking-decaluwe20-local-20261114/audit.json) |
| 21 | BIOMD0000000203 | 24 | Validated | [Audit](../catalog-breaking-original-completed/audit.json) |
| 22 | BIOMD0000000204 | 30 | Validated | [Audit](../catalog-breaking-original-completed/audit.json) |
| 23 | BIOMD0000000209 | 32 | Validated | [Audit](../catalog-breaking-original-completed/audit.json) |
| 24 | BIOMD0000000210 | 138 | Validated | [Audit](../catalog-breaking-original-completed/audit.json) |
| 25 | BIOMD0000000539 | 118 | Unfinished | Awaiting complete audit |
| 26 | BIOMD0000000664 | 118 | Validated | [Audit](../catalog-breaking-muller26-full-recovery/audit.json) (other runs retained in index) |
| 27 | BIOMD0000000275 | 22 | Validated | [Audit](../catalog-breaking-linux-27/audit.json) (other runs retained in index) |
| 28 | BIOMD0000000697 | 622 | Initial cases complete; validation fails | [Audit](../catalog-breaking-linux-28/audit.json) |
| 29 | BIOMD0000000600 | 1088 | Unfinished | Awaiting complete audit |
| 30 | BIOMD0000000039 | 38 | Initial cases complete; validation fails | [Audit](../catalog-breaking-linux-30/audit.json) (other runs retained in index) |
| 31 | BIOMD0000000050 | 728 | Validated | [Audit](../catalog-breaking-linux-31/audit.json) |
| 32 | BIOMD0000000035 | 204 | Unfinished | Awaiting complete audit |
| 33 | BIOMD0000000036 | 0 | Validated; no eligible cases | [Audit](../catalog-breaking-linux-33/audit.json) |
| 34 | BIOMD0000000037 | 360 | Validated | [Audit](../catalog-breaking-linux-34/audit.json) |
| 35 | BIOMD0000000038 | 260 | Unfinished | Awaiting complete audit |

The unfinished networks are **2, 5, 15, 25, 29, 32 and 35**. Networks **3, 8, 11, 28 and 30** have terminal initial-case inventories with remaining numerical failures or unresolved conditional paths. Later diagnostic and control work is documented separately and cannot change these counts until the required complete-case and model audits pass.

Rebuild the index from the repository's `python` directory:

```sh
uv run --locked python results/catalog-breaking-coverage-20261114/build_index.py \
  --source . --output /path/to/recomputed-breaking-index.json
```

The script verifies all 35 catalog identities and candidate counts against each included complete-model audit. It reads only tracked `catalog-breaking*/audit.json` files, so newer committed audits will update the index. It does not rerun solvers or substitute this inventory check for their numerical audits. This snapshot does not claim that the active all-35 goal is complete.
