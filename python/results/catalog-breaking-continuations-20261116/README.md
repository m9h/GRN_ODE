# Continue the remaining original partitions

Fifteen stopped, incomplete Linux partitions passed fresh checkpoint preparation
before dispatch: Tyson network 5 indices 13–15; François network 25 indices
14–15; and Cellière network 29 indices 1, 2, 5, 6, 7, 9, 11, 13, 14, 15.
All had reached their five-hour budgets. `dispatch.json` records the exact new
run IDs, job IDs, original parent runs and unchanged numerical producer revision.

The three `network-*-verification.json` files preserve original ZIP hashes,
complete extracted-file verification, the selected case keys, and validated
checkpoint counts. Every source was freshly extracted and checked against the
actual numerical code and installed packages before preparation. Failed case
aggregates remain in history and must be recomputed; passing selected cases
are reused only after their complete conditional histories pass the auditor.

Tyson's three parents added 52 branch checkpoints. Cellière's ten added 35,872.
No inherited checkpoint changed. François's initial partitions retained 228
branch checkpoints and four passing case checkpoints. No solver setting,
comparison tolerance, control, horizon or case selection was changed.

Each `network-*-combined-plan.json` fixes all sixteen partition identities,
combining unchanged completed partitions with these continuations. The existing
continuation auditor watches those plans and requires complete model coverage;
it stops for another continuation if a selected partition is still incomplete.
Dispatching a job does not establish numerical validation.

Tyson and Cellière remain the two models without a complete initial inventory.
François already has a complete macOS inventory with failures; finishing its
Linux computation provides a separate reproduction. The [coverage report](../catalog-breaking-coverage-20261116/README.md)
preserves that distinction.
