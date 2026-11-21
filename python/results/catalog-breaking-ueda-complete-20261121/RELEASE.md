Ueda's circadian-clock model (`BIOMD0000000022`, network 11) has a combined
302/302 passing breaking-case audit: 298 original passes plus four recovered
cases with complete independent controls.

This release preserves all 32 original cloud ZIPs and the original whole-model
evidence archive: **33 evidence assets, 9,864,801,068 bytes**. `SHA256SUMS` and
`release-manifest.json` bind every original byte. The recovery includes 323
branches, 1,292 complete trajectories and 1,938 passing comparisons. The
original 298 passes are reaudited from saved comparison records and window
summaries; their full raw trajectories were not archived.

The separately published `kinetics-ueda-preservation-20261118` release is a
required, checksum-pinned dependency. Its files are not duplicated here.
The original failures remain preserved. No new simulation, changed tolerance
or reduced case selection was used to package this release.

See `python/results/catalog-breaking-ueda-complete-20261121/REPRODUCE.md` at
this release tag for the full offline audit procedure after downloading both
releases. A full Git clone is required to verify historical source revisions.

This result validates the specified numerical protocols; it does not by itself
establish the philosophical thesis of *Ingressing Minds*. The all-model goal
remains incomplete: 27 of the 35 whole-model breaking audits currently pass.
