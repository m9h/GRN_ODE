# Reproduce the complete Ueda audit

This procedure downloads two evidence releases, validates their original
bytes, restores the preserved evidence, audits all 323 recovery branches,
replays all four recovered cases, and combines them with the original
298 passing cases. It performs no ODE integration. It leaves the original
failures in the evidence and does not change any comparison threshold.

Use a full clone, Python 3.12, `uv`, GitHub CLI (`gh`), `tar` and
`shasum`. Allow about 100 GB of free space for downloads, separate extraction,
assembly and the Python environment. Download size is approximately 21.54 GB.
Use a fresh output directory. The preservation and assembly steps refuse to
overwrite an existing reproduction.

## Download and verify

From a full clone of `m9h/GRN_ODE`:

```sh
git checkout kinetics-ueda-complete-20261121
cd python
uv sync --locked --extra test --extra jaxkineticmodel

ueda_root="$PWD/results/ueda-release-reproduction"
mkdir "$ueda_root"
gh release download kinetics-ueda-complete-20261121 --repo m9h/GRN_ODE \
  --dir "$ueda_root/assets"
cmp results/catalog-breaking-ueda-complete-20261121/release-manifest.json \
  "$ueda_root/assets/release-manifest.json"
cmp results/catalog-breaking-ueda-complete-20261121/SHA256SUMS \
  "$ueda_root/assets/SHA256SUMS"
(
  cd "$ueda_root/assets"
  shasum -a 256 -c SHA256SUMS
)

gh release download kinetics-ueda-preservation-20261118 --repo m9h/GRN_ODE \
  --dir "$ueda_root/preservation-assets"
uv run --locked --extra test --extra jaxkineticmodel python \
  results/catalog-breaking-ueda-continuation-20261118/reproduce.py reproduce \
  --assets "$ueda_root/preservation-assets" --output "$ueda_root/prior"
```

The preservation reproducer and its manifest are copied byte-for-byte from
`07568199b113fee32f99d3feefed38e6d845b01c`. Its preparation source and inputs
are unchanged. It verifies every asset and extracted file, then requires three
fresh preparation outputs to match their published hashes exactly. The
historical output correctly says no case has yet recovered at that stage.

## Audit the complete recovery

Continue in the same shell, from `python/`:

```sh
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/collect_ueda_continuation.py collect \
  --inputs results/catalog-breaking-ueda-continuation-20261118 \
  --selection results/catalog-breaking-ueda-complete-20261121/selection.json \
  --snapshots results/catalog-breaking-ueda-complete-20261121/api \
  --archives "$ueda_root/assets" --output "$ueda_root/collection" \
  --assemble "$ueda_root/assembled" \
  --preserved "$ueda_root/prior/preserved" \
  --restored "$ueda_root/prior/preparation/restored-imports"
```

The fixed selection contains all 32 partitions. Original API snapshots bind
each job, attempt, producer revision and ZIP digest. The snapshots preserve
the artifacts' state at collection; verification now reads the release assets
offline. Collection rejects missing, altered or extra evidence. Assembly uses
156 complete preserved branches, 24 published imports with ten overlaps, and
153 new branches. It checks all 1,292 arrays and 1,938 comparisons, including
the full untreated baseline and every required conditional control.

Expected `assembled/audit.json`: four selected cases, four recovered cases,
323 confirmed branches, a passing baseline, and no previously passing
branches requiring revalidation. The largest scaled comparison error is
0.7800395088623073, below the unchanged threshold of 1.

## Reaudit the original inventory and combine

```sh
tar -xzf "$ueda_root/assets/breaking-network11-local-20261113.tar.gz" \
  -C "$ueda_root"
mv "$ueda_root/catalog-breaking-ueda11-local" "$ueda_root/original-model"
cp results/catalog-breaking-ueda-complete-20261121/original-model-report.json \
  "$ueda_root/original-model/BIOMD0000000022.json"
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/audit_breaking_catalog.py --input "$ueda_root/original-model" \
  --network 11 --source-revision 70a3afad61357e94873ff62a7300c099b4c7ae3e \
  --output "$ueda_root/original-model/reproduced-audit.json"

cp results/catalog-breaking-ueda-complete-20261121/combine_model_audits.py \
  "$ueda_root/combine_model_audits.py"
uv run --locked --extra test --extra jaxkineticmodel python \
  "$ueda_root/combine_model_audits.py"
```

The original audit must retain 302 cases, 298 passes, four failures,
13,315 branch records and zero unresolved conditional decisions. It prints
`Numerical validation of selected models: False`; this is the preserved
original result, not a reproduction error. Its archive contains saved
pointwise comparison records and window summaries, not the full raw arrays.

The final check requires the exact four original failures to match the four
complete independent recoveries, with unchanged conditional paths. It writes
`combined-model-audit.json` with 302 passing cases and a source for every
case. Reproduction timestamps, local paths and hashes of reports containing
them will differ. Scientific inventories, array identities, classifications
and comparison results must agree. Do not compare time-dependent report
hashes as if they were original evidence-file hashes.
