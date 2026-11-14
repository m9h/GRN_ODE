# Vilar precision continuation from the terminal second run

Run [43483480217](https://github.com/m9h/GRN_ODE/actions/runs/43483480217) is terminal and all 17 artifacts were collected. Seven partitions contain complete RoadRunner, 128-bit Taylor and 192-bit Taylor trajectories. Ten partitions still require work: 3, 6, 7, 8, 9, 10, 11, 13, 14 and 16.

The continuation restores all 17 original selections. Completed trajectories are reused only after validation; unfinished integrations resume from their exact saved state. The plan records every original artifact and member hash, the common producer environment, and the unchanged numerical implementation. Serialized MPFR checkpoints undergo semantic validation in the matching Linux runtime before further integration.

Every original sample, intervention, reset and tolerance is retained. A stopped run is not treated as a numerical success. Complete trajectories with RoadRunner mismatches remain mismatches. This continuation includes all 16 original failed branches and the untreated baseline; it does not replace the separate 23-control batch or establish complete-case recovery.

`plan.json` records the verified terminal parent evidence. `dispatch.json` records the actual new run and its producer revision after dispatch. The numerical implementation remains unchanged from the pinned source in the plan. The workflow uses uv, Python 3.12.12 and Heyoka 7.13.2.
