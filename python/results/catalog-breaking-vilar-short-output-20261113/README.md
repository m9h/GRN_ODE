# Initial Vilar output diagnostic

This first capture ran three declared original branches at the original and
two tighter settings in both native solvers. All nine COPASI outputs were
incomplete; no branch or case was recovered.

The capture preserved complete RoadRunner trajectories and raw partial COPASI
arrays. COPASI's global message queue contained annotation warnings after
Basico consumed the solver errors. The subsequent
[logged repeat](../catalog-breaking-vilar-short-output-logged-20261113/README.md)
preserves those errors separately and independently recomputes its full-array
comparisons. Both attempts are retained in the release; their stopping times
are not silently substituted for each other.
