# Reproduce the Ueda evidence snapshot

This package preserves the inputs to the cloud continuation. It does not claim
that the four selected cases have recovered. The full experiment still requires
323 distinct branches; 170 currently have complete preserved or published
evidence, while 153 remain assigned to the fixed cloud computation.

The local-package reproduction passed: all three preparation outputs match
byte for byte, as recorded in `local-package-reproduction.json`. The draft
release upload and fresh release-download check are still in progress; the
release will be published only after the fresh-download check passes.

## Contents and scientific scope

The package contains eleven uncompressed tar parts holding all 787 available
snapshot files, plus the exact original published Ueda diagnostic archive.
Together these twelve evidence assets occupy **11,671,643,854 bytes**. A separate
`release-manifest.json` binds every asset's size and SHA-256 and every snapshot
member's name, size and SHA-256. The manifest itself is pinned in this repository.

The snapshot contains 628 verified arrays: 624 belong to 156 complete branches,
and four belong to two incomplete evidence sets. Fourteen historically reported
records and three arrays from another reported branch are absent; they are
explicitly accounted for by the continuation plan. The reason for their absence
is unknown. The older published diagnostic supplies 24 branches, ten overlapping
the complete snapshot branches. It restores two missing historical imports
exactly and supplies twelve previously unprocessed imports.

The preparation audit checks every available observation, all observables,
resets, model/source identity, numerical requests and recorded comparisons.
It then recreates all published imports and derives all 153 missing branch
identities. The three resulting files must reproduce **byte for byte**:

- `preserved-audit.json`
- `restoration-proof.json`
- `continuation-plan.json`

There are no timestamp or numerical-field exceptions. An altered scientific
result, a missing file, changed asset/member bytes, a symlink or an escaping
archive path causes verification to fail. All eleven transport tests pass
locally. Original numerical source and environment files remain unchanged.

## Download and reproduce offline

Use a full clone so the original source revisions remain available. Allow about
35 GB of free disk space for the download, extracted snapshot and restored
diagnostic evidence. The reproducibility command performs no ODE integrations
and makes no network requests after the downloads and uv environment setup.

```sh
git clone https://github.com/m9h/GRN_ODE.git
cd GRN_ODE
git checkout kinetics-ueda-preservation-20261118
cd python
uv sync --locked --extra test --extra jaxkineticmodel
gh release download kinetics-ueda-preservation-20261118 --repo m9h/GRN_ODE \
  --dir /path/to/fresh-ueda-assets
uv run --locked --extra test --extra jaxkineticmodel python \
  results/catalog-breaking-ueda-continuation-20261118/reproduce.py reproduce \
  --assets /path/to/fresh-ueda-assets --output /path/to/new-ueda-reproduction
```

`reproduction-verification.json` records the exact preparation-output hashes,
manifest and reproducer hashes, verified array counts, preserved/imported branch
counts and the remaining work. It explicitly records zero numerical integrations
and no case or whole-model recovery claim. The unchanged final case auditor will
run only after the selected cloud evidence has been collected; see
[COLLECTION.md](COLLECTION.md).

To rebuild the transport package from the preserved source directory and its
downloaded diagnostic archive, use `reproduce.py pack --evidence EVIDENCE_ROOT
--assets NEW_ASSET_DIRECTORY`. Both packing and reproduction require a new
destination and preserve the original files.
