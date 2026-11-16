# Vilar precision checkpoint progress

Run [43556371440](https://github.com/m9h/GRN_ODE/actions/runs/43556371440) is
terminal. All 17 original artifacts are retained and their ZIP and member
hashes were rechecked. Eleven partitions now contain complete RoadRunner,
128-bit Taylor and 192-bit Taylor arrays. Six remain incomplete: 6, 8, 9, 10,
11 and 16. Complete arrays and native mismatches remain separate outcomes;
no additional paired case has been recovered.

`plan.json` captures the complete original selection, common producer
environment, unchanged numerical implementation and all artifact identities.
`checkpoint-progress.json` compares saved state against the previous parent
run, 43483480217. Five unfinished partitions advanced. Partition 10 completed
128-bit integration and advanced its 192-bit run to 20,010 saved samples.

Partition 6 did **not** advance its saved checkpoint: both runs retain 9,900
samples, 490/500 completed segments, and the last completed interval
`[98.9, 99.0]`. The checkpoint payload hash is identical. This establishes no
saved progress through another five-hour job; it does not establish a
mathematical singularity or absence of work within the interrupted segment.

No new precision batch was dispatched from this plan. Repeating that unchanged
partition would again discard work inside a segment if it exceeds the job
deadline. The next step is to investigate checkpointing within long segments
or another validated execution strategy while preserving the complete horizon,
observation grid, reset schedule and both precisions. The five advancing
partitions remain in scope and can be continued independently once the workflow
supports a fixed partial selection. The full-model audit must still include
all seventeen original partitions and the separate case-control inventory.

Exact MPFR state and schedule-counter validation must occur in the matching
Linux runtime before any resumed integration. This read-only inspection used
uv and did not change the live numerical source or environments.
