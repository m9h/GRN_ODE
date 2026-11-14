# Targeted Tyson continuation

Network 5 is the six-variable Tyson cell-cycle model (BioModel 5), with 58
initial breaking cases. Partitions 13 and 15 of run 43485099563 stopped at
their five-hour budgets. They added 22 and 19 atomic branch checkpoints,
respectively; no inherited checkpoint changed. This is progress within full
conditional case searches, even though no additional complete cases were saved.

Both original artifact ZIP hashes were verified, then their fresh extractions
passed the real restoration checks against the current numerical source and
installed packages. Partition 13 restores 90 branches and one passing case;
partition 15 restores 43 branches. `verification.json` records the exact
artifact identities, checksums, selections and preparation results.

The dispatched jobs are [partition 13](https://github.com/m9h/GRN_ODE/actions/runs/43560384864)
and [partition 15](https://github.com/m9h/GRN_ODE/actions/runs/43560386302).
`dispatch.json` records their exact producer revision and job identities.

The continuations keep the original 16-partition scheme and seven selected
cases. One of those cases is already recorded as passed; the six other cases
still require completion and audit. Only indices 13 and 15 are restarted.
Partition 14 remains in the original run. No solver settings, controls,
observation horizons or acceptance thresholds change.

The full-model audit must eventually use all sixteen disjoint partitions,
taking 13 and 15 from their targeted continuations and the other fourteen
from run 43485099563, unless a later documented continuation is needed. Each
partition retains its own branch evidence. A dispatched or completed partial
job does not by itself establish complete-model validation.
