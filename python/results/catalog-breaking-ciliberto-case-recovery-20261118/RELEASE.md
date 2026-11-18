# Reproduce the complete Ciliberto case audit

The package contains 37 evidence assets totaling 19,274,473,811 bytes: eighteen
archives of the original preserved snapshot, one archive of the exact restored
import, and all eighteen original replacement ZIPs. The separate
[manifest](release-manifest.json) binds each asset's size and SHA-256 and every
preserved archive member. The original API snapshot, plans, reports, complete
audit and source references are retained in this pinned repository directory.

The release tag used below is `kinetics-ciliberto-cases-20261118`. The completed
scientific audit is documented in [COMPLETED_AUDIT.md](COMPLETED_AUDIT.md).
Release notes record publication and fresh-download reproduction separately
from the original scientific audit.

Use a full clone so that the collector can inspect the pinned producer commit:

```sh
git clone https://github.com/m9h/GRN_ODE.git
cd GRN_ODE
git checkout kinetics-ciliberto-cases-20261118
cd python
uv sync --locked --extra test --extra jaxkineticmodel
gh release download kinetics-ciliberto-cases-20261118 --repo m9h/GRN_ODE --dir results/ciliberto-release-download
uv run --locked --extra test --extra jaxkineticmodel python results/catalog-breaking-ciliberto-case-recovery-20261118/reproduce.py reproduce \
  --assets results/ciliberto-release-download \
  --output results/ciliberto-release-reproduction
```

Allow about 65 GB of free disk space for the downloads, fresh extraction and
assembled audit evidence. The output directory must be new. The script uses
saved arrays only and performs no numerical integrations or network requests.

The reproducer verifies all downloads against the repository manifest, rejects
unsafe or incomplete archives, checks every preserved member, and invokes the
unchanged collector for all 18 fixed replacement branches. Assembly uses all
196 unaffected branches, the exact restored import and every predetermined
replacement. The unchanged case auditor then reads all 215 branches and 860
trajectories and reconstructs every control, conditional search and classification.

The fresh assembled report must equal the published report except for its actual
assembly finish time. The complete audit must equal the published audit except
for the resulting report checksum. No numerical values, classifications, failed
comparisons or coverage fields are excluded. `reproduction-verification.json`
records both audit hashes and the comparison rule.

The ten release-transport tests and forty-five existing collection/selection/audit
tests pass locally. They include changed payloads with updated outer checksums,
path traversal, symlinks, missing members and scientific-result changes.
Synthetic tests establish transport behavior; fresh reproduction of the real
dataset is required separately.
