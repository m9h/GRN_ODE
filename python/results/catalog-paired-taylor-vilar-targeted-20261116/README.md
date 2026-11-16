# Continue the five advancing precision partitions

The precision workflow now accepts an optional JSON list of **original**
partition indices. The default still computes the complete inventory. A gate
rejects duplicate, empty, non-integer and out-of-range selections before creating
computation jobs. The original count (17 for Vilar, four for Marhl), partition
identities, reset schedules and numerical implementation remain unchanged.

For terminal parent run 43556371440, indices **8, 9, 10, 11 and 16** made saved
checkpoint progress and are selected for continuation. The [parent inspection](../catalog-paired-taylor-vilar-continuation-20261116/README.md)
verifies all seventeen original artifact ZIPs, their member hashes, complete
saved arrays and unchanged model/implementation identities. Exact MPFR state
validation remains mandatory in the matching Linux runtime before resuming.

Partition 6 retains the identical checkpoint after another five-hour job and
requires investigation of work lost inside a long integration segment. It is
still an outstanding part of the complete inventory. The eleven completed
partitions are retained from the parent run. This five-partition continuation
does not claim complete-model coverage or additional paired-case recovery.

Validation: actionlint passes, and fourteen direct executions of the workflow's
Python selection gate cover full defaults for both models, valid subsets, and
invalid inputs. The dispatched workflow additionally runs its existing numerical
checkpoint tests before any integration. `dispatch.json` records the actual run
and producer once dispatched.
