# Retained Vilar precision evidence, with the complete 17-partition selection

This release preserves **27 exact original GitHub artifact ZIPs** (138,604,939
bytes), including the ancestors of the current selection. All **17 original
partitions** remain required: the untreated baseline and sixteen originally
failed paired-protocol branches. Thirteen partitions have complete arrays;
partitions **8, 9, 11 and 16 remain incomplete**.

Fresh local reproduction checks **39 complete trajectories** and reproduces
every saved pointwise comparison. Four complete partitions agree across the
three integrations: the baseline and branches 1, 2 and 4. The other nine have
agreement between 128-bit and 192-bit Taylor integration but retain a mismatch
with RoadRunner. These are branch diagnostics, not recovered memory cases.
The three unresolved paired cases and the full case/control audit remain open.

## What is compared

Each complete diagnostic retains RoadRunner (`rtol=1e-13`, `atol=1e-15`),
128-bit Taylor (`tol=1e-30`) and 192-bit Taylor (`tol=1e-45`) outputs. The
unchanged comparison thresholds are `rtol=2e-5`, `atol=1e-7`. Full protocol
branches cover 300 time units and all 30,001 original observations with the
original reset schedule. The baseline covers its original shorter interval.
The saved observation arrays are binary64; exact MPFR restart state is stored
separately in checkpoints.

Agreement between the two Taylor runs is evidence of convergence under these
precision choices and checks. It is not a proof of the exact solution or a
reason to discard the native mismatch. The release retains all outcomes.

## Source versions remain explicit

Twelve complete partitions predate the change that permits checkpoints inside
long integration segments. The current auditor correctly rejects their older
source fingerprints. Their original arrays are therefore checked using the
unchanged legacy source `56bbfefe90f6b2a2ebeefcb4ea5d7706451deaf0`; the other
complete partition and four current checkpoints use the segment-checkpoint
source. Every worker runs in a separate process with pinned audit-file hashes.
The model, initial failure inventory, requests, observation grid, acceptance
thresholds and producer environment match across both groups. The implementation
versions are not relabeled or claimed to produce identical trajectories.

`manifest.json` binds all original archives, complete API snapshots, actual
run/job/artifact identities, selected reports and expected scientific audits.
The reproducer verifies all 27 ZIPs, rechecks each selected report with its
matching source, reloads all complete arrays, and requires exact equality with
the thirteen recorded numerical audits. It also checks the four partial
checkpoint payload hashes and observation checksums. Semantic validation of
native MPFR state remains required in the matching Linux runtime before resume.

The latest incomplete checkpoints contain 13,698, 13,846, 13,716 and 13,485
observations respectively. Their continuation runs remain separate from this
immutable release. A newly completed trajectory must be collected and audited
before it changes any completion count.

## Reproduce

Check out the `precision-vilar-retained-20261126` release tag of this repository.
Create the second pinned source checkout, then use the same Python environment
for both offline auditors:

```sh
git worktree add --detach /tmp/vilar-legacy 56bbfefe90f6b2a2ebeefcb4ea5d7706451deaf0
cd python
uv sync --locked --extra test --extra jaxkineticmodel
gh release download precision-vilar-retained-20261126 --repo m9h/GRN_ODE --dir /tmp/vilar-release
cd /tmp/vilar-release
shasum -a 256 -c SHA256SUMS
tar -xzf vilar-original-archives.tar.gz
```

Return to the release checkout's `python` directory and run:

```sh
uv run --locked --extra test --extra jaxkineticmodel \
  python results/catalog-paired-vilar-retained-20261126/reproduce.py \
  --legacy-python-root /tmp/vilar-legacy/python \
  --archives /tmp/vilar-release/originals --output /tmp/vilar-fresh-audit
```

Use a new output directory. The expected result is 27 original ZIPs verified,
all 17 selected partitions checked, 13 complete diagnostics, 39 complete arrays,
four agreements including the baseline, nine precision-converged native
mismatches, and four unfinished checkpoints. No integrations, network calls or
workflow submissions occur during the audit itself.
