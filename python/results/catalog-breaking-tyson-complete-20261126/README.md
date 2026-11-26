# Complete Tyson1991 recorded case inventory

All **58 cases in sixteen partitions** now have auditable original evidence.
The unchanged full audit reproduces **55 passing cases and three failures**:
`C2__up--M__down`, `pM__down--M__down`, and `pM__up--M__down`.
There are **2,189 branch records**, representing **1,970 distinct branch
specifications**, and no unresolved conditional decisions. This completes the
missing-evidence recovery; it does not establish a whole-model numerical pass.

Partitions 0–13 were recomputed after historical ZIPs expired and their temporary
local copies became unavailable. Partitions 14–15 are the preserved original
outputs. Every partition uses producer
`cae38e9a6ec4c7567ea6cbf2908778f409a1ebb0`, the same model/reference data, numerical
settings and environment fingerprint. `selection.json` binds the actual jobs,
attempts and producer revisions. The final partition-13 continuation preserved
all 111 preceding branch records and two case records byte for byte.

The release retains all **sixteen original ZIPs (22,044,004 bytes)** without
recompression, plus a manifest with every extracted file hash. These contain
recorded solver comparisons and response-window summaries, not complete raw
trajectory arrays. Reproduction rechecks the recorded evidence and original
case-scoring logic; it cannot provide a new pointwise trajectory comparison.
Failures remain in the evidence and are not relabeled as successes.

## Reproduce from the release

Check out the `kinetics-tyson-complete-20261126` release tag of this repository,
then from its `python` directory:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
gh release download kinetics-tyson-complete-20261126 --repo m9h/GRN_ODE --dir /tmp/tyson-originals
uv run --locked --extra test --extra jaxkineticmodel \
  python results/catalog-breaking-tyson-complete-20261126/reproduce.py \
  --assets /tmp/tyson-originals --output /tmp/tyson-fresh-audit
```

The output directory must be new. The script checks the pinned manifest, complete
selection, exact ZIP bytes, safe member paths and complete file inventory, then
calls the unchanged scientific auditor for all 58 cases. Its result must equal
`expected-audit.json`, allowing only the sixteen extraction directory paths to
differ. No integrations or workflow submissions occur during reproduction.
