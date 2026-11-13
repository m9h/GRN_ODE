# Network 35 checkpoint continuation

The parent run stopped with 249 of 260 case results recorded. Of those, 131
passed numerical validation. Partitions 5 and 7 have incomplete selections;
the other fourteen partitions have complete case coverage, including their
explicit numerical failures.

`plan.json` binds all sixteen terminal parent artifacts, reports, candidate
selections and calibration. The current numerical source hashes match the
parent records. Full semantic checks of the atomic checkpoints run in the
matching CI environment before any continuation.

[Run 43513140878](https://github.com/m9h/GRN_ODE/actions/runs/43513140878)
retains the sixteen-way partitioning. Completed cases are reused; the two
incomplete selections continue from their checkpoints. The model, controls,
conditional searches, observation grids and acceptance thresholds remain the
original requests. The producer is `e891478b94fb732a3c4bd2e799eb7af35ace6f2a`.

`dispatch.json` records the actual workflow and complete partition matrix.
This continuation is not evidence that network 35 has completed or passed.
