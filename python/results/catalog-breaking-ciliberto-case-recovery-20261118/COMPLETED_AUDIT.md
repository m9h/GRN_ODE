# Both selected Ciliberto cases pass the complete audit

On 18 November 2026, the complete saved-array audit recovered both selected
cases, `Cdk2_CycE__down--Kin_a__up` and `Cdk2_CycE__up--Kin_a__up`.
The full untreated baseline also passes. The audit checks all **215 branches
and 860 full trajectories**, with the original observation grids, reset
schedules, solver requests and acceptance thresholds.

The [fixed cloud run](https://github.com/m9h/GRN_ODE/actions/runs/44250781579)
finished all 18 replacement jobs. Collection verified all original ZIPs,
72 replacement arrays and 108 pairwise comparisons, with no collection errors.
Assembly retained 196 unaffected original branches, restored one imported
branch exactly from its published archive, and used all four newly computed
requests for every one of the 18 predetermined replacements. The untouched
historical snapshot and original report remain separate.

The unchanged case auditor independently reads every saved observation,
recomputes comparisons and response windows, and reconstructs conditional
searches and controlled classifications. Its complete result is preserved in
[completed-audit.json.gz](completed-audit.json.gz); the
[summary](completed-audit-summary.json), [collection verification](completed-collection-status.json),
[assembly provenance](completed-assembly-provenance.json),
[assembled producer report](completed-producer-report.json) and
[GitHub API snapshot](completed-api) retain the supporting records.

The uncompressed audit SHA-256 is
`7d67101f2d2531611710edbd142fee97c7d46162cf0572446a6fb454acbf7383`.
The numerical producer is pinned to `843fbd136ce0301f475818524ae9c7d3e2280819`;
the collection and assembly code is `7b92b82c43f609259d08d7447fffb7ab2b275149`.
Its 45 targeted tests also passed in the
[Linux validation run](https://github.com/m9h/GRN_ODE/actions/runs/44253556385).

This establishes recovery of these two selected cases. The separate original
full-model result remains **548/622 passing cases, with 74 failures**. Historical
passes have not been combined with these calculations to claim a new whole-model
total. No local numerical workers were resumed for this repair.

The complete assembled evidence is preserved outside temporary storage. The
full trajectory package, checksums and fresh-download reproduction procedure
are described in [RELEASE.md](RELEASE.md). The committed audit is not a substitute
for those trajectory files. See [COLLECTION.md](COLLECTION.md) for the collection
and assembly procedure; release notes record publication and reproduction status.
