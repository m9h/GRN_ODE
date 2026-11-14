# Vilar checkpoint restoration repair

Partition 7 of [run 43485109761](https://github.com/m9h/GRN_ODE/actions/runs/43485109761/job/132091375493)
stopped before simulation while checking its parent artifact. Five inherited
case aggregates did not reproduce their saved scores from the available branch
records. All five were already marked failed and lay outside this partition's
13 selected initial cases. This was a checkpoint restoration failure, not a new
numerical result.

The corrected preparation validates all 2,288 branch checkpoints and the five
passing selected case aggregates, then copies those 2,293 files into the active
cache. It preserves all 43 other case aggregates byte for byte in a separate
history directory. Every case identity is checked; a selected passing case with
nonreproducing scores still fails preparation. Failed selected cases require
recomputation. The model equations, solver settings, controls, observation grids
and acceptance tolerances are unchanged.

`verification.json` records a fresh extraction and preparation of artifact
14028918797 from run 43273680209. The original ZIP is 55,168,150 bytes, SHA-256
`17b728dc9b438becc054ff1300dfe09fa3dc52ae237cb8551f233aada7f7a551`.
The exact ZIP is preserved in the [checkpoint evidence release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-vilar-resume-repair-20261114).
Its source files, active checkpoint copies and preserved case history all match
their original bytes. Preparation performs zero integrations and makes no model
completion claim. The five historical discrepancies remain explicit evidence.

From `python/`, with the locked dependencies installed:

```bash
uv run --locked --extra delay python \
  results/catalog-breaking-network32-resume-repair-20261114/reproduce_preparation.py \
  --archive /path/to/original-artifact.zip --output /tmp/fresh-resume-verification
```

The output directory must not exist. The script checks the ZIP hash, reproduces
the five historical audit failures, runs the real preparation checks against
the installed environment, and verifies that the source remains unchanged.

Validation: 35 checkpoint, partition and evidence-audit tests through uv; the
workflow passes actionlint. The targeted repair keeps index 7 of the original
16-partition inventory. It does not restart the other partitions or change
the all-35-model coverage counts.

The [targeted repair run](https://github.com/m9h/GRN_ODE/actions/runs/43559717170)
contains only partition 7; `dispatch.json` binds its producer and parent artifact.
The final full-model audit must combine this partition with the other fifteen
from run 43485109761 after their selected inventories finish, retaining each
partition's own branch evidence.
