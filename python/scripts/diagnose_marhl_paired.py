"""Reproduce late numerical divergence in three Marhl paired-protocol branches.

This diagnostic deliberately retains the full 0..300 horizon and the existing
pointwise acceptance threshold. Successful execution does not mean validation
passed: inspect all_full_horizon_comparisons_passed in the JSON report.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt
import numpy as np

from grn_memory.catalog_paired import branch_spec, branch_id, reset_trains
from grn_memory.catalog_validation import comparison, PACKAGES
from grn_memory.native_protocols import ResetTrain, sample_times, protocol_trajectory


def diagnose(output):
    output.mkdir(parents=True, exist_ok=True)
    path = ROOT / "models/BIOMD0000000039.xml"
    source = ROOT / "results/catalog-memory/BIOMD0000000039.json"
    reference = json.loads(source.read_text())
    requests = [(1e-12, 1e-14), (1e-13, 1e-15), (3e-14, 3e-16)]
    specs = [
        branch_spec(["CaER__down", "CaM__up"], "CaER__down", 150.),
        branch_spec(["Ca_cyt__up"], "CaER__down", 150.),
        branch_spec(["CaER__down", "Ca_cyt__up"], "CaER__down", 150.),
    ]
    times = sample_times(300., .01, [ResetTrain(t, t+50., {}) for t in (50., 150., 200.)],
                         post_reset_offset=1e-5)
    result = {
        "purpose": "Diagnose full-horizon trajectory disagreement without changing the acceptance test",
        "model": "Marhl2000_CaOscillations", "network": 30, "biomodel_id": "BIOMD0000000039",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "model_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "reference_file_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "versions": {p: version(p) for p in PACKAGES},
        "implementation_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__).resolve()] + [ROOT / "grn_memory" / name for name in
                      ("native_protocols.py", "catalog_validation.py", "catalog_paired.py", "simulation.py")]
        },
        "configuration": {"duration": 300., "sample_count": len(times), "dt": .01,
                          "post_reset_offset": 1e-5, "requests": requests,
                          "comparison_atol": 1e-7, "comparison_rtol": 2e-5},
        "branches": [],
    }
    fig, axes = plt.subplots(3, 2, figsize=(12, 9), constrained_layout=True)
    for index, spec in enumerate(specs):
        trains = reset_trains(spec, reference)
        traces = {}
        row = {"specification": spec, "branch_id": branch_id(spec), "runs": {}, "comparisons": {}}
        for engine in ("roadrunner", "copasi"):
            for rtol, atol in requests:
                key = engine + "_" + str(rtol)
                try:
                    trace = protocol_trajectory(path, times, trains, engine, rtol=rtol, atol=atol)
                except (RuntimeError, ValueError) as exc:
                    row["runs"][key] = {"error": f"{type(exc).__name__}: {exc}"}
                    continue
                traces[key] = trace
                row["runs"][key] = {"rtol": rtol, "atol": atol,
                    "minimum": trace.iloc[:, 1:].min().to_dict(),
                    "maximum": trace.iloc[:, 1:].max().to_dict()}
        for rtol, atol in requests:
            keys = [e + "_" + str(rtol) for e in ("roadrunner", "copasi")]
            if not all(k in traces for k in keys):
                continue
            a, b = (traces[k] for k in keys)
            x, y = a.iloc[:, 1:].to_numpy(), b.iloc[:, 1:].to_numpy()
            scaled = np.max(np.abs(x-y) / (1e-7 + 2e-5*np.maximum(np.abs(x), np.abs(y))), axis=1)
            failed = np.flatnonzero(scaled > 1)
            windows = {}
            for end in (50., 100., 150., 200., 250., 300.):
                mask = (times >= end-50.) & (times <= end)
                windows[str(end)] = comparison(a.loc[mask].reset_index(drop=True), b.loc[mask].reset_index(drop=True))
            row["comparisons"][str(rtol)] = {
                "full": comparison(a, b),
                "through_normal_recall_end": comparison(a.loc[times <= 250.], b.loc[times <= 250.]),
                "first_outside_tolerance": float(times[failed[0]]) if len(failed) else None,
                "windows": windows,
            }
            axes[index, 1].semilogy(times, np.maximum(scaled, 1e-12), label=f"rtol {rtol:g}")
        for engine in ("roadrunner", "copasi"):
            a, b = engine + "_1e-13", engine + "_3e-14"
            if a in traces and b in traces:
                row["comparisons"][engine + "_refinement"] = comparison(traces[a], traces[b])
            if a in traces:
                trace = traces[a]
                mask = times >= 250.
                axes[index, 0].plot(times[mask], trace.Ca_cyt[mask], label=engine,
                                    linestyle="-" if engine == "roadrunner" else "--", linewidth=1.1)
        axes[index, 0].set(title="Train: " + ", ".join(spec["training"]), ylabel="Cytosolic calcium", xlim=(250, 300))
        axes[index, 0].legend(fontsize=8)
        axes[index, 1].axhline(1., color="black", linestyle=":", label="acceptance limit")
        axes[index, 1].set(ylabel="Maximum normalized difference", xlim=(0, 300))
        axes[index, 1].legend(fontsize=8, ncol=2)
        result["branches"].append(row)
    for ax in axes.flat:
        ax.set_xlabel("Native model time")
        ax.grid(alpha=.2)
    fig.suptitle("Marhl paired protocols: late numerical divergence\nNormal cue at 150–200; normal recall ends at 250", fontsize=13)
    fig.savefig(output / "late-divergence.png", dpi=160)
    plt.close(fig)
    comparisons = [r["comparisons"].get(str(rtol)) for r in result["branches"] for rtol, _ in requests]
    result["all_full_horizon_comparisons_passed"] = all(c and c["full"]["passed"] for c in comparisons)
    result["all_comparisons_through_normal_recall_passed"] = all(c and c["through_normal_recall_end"]["passed"] for c in comparisons)
    result["interpretation"] = (
        "Late pointwise convergence is not established. Agreement through time 250 supports only the earlier "
        "normal-cue and normal-recall windows of these branches. This diagnostic does not establish chaos "
        "or validate the 250..300 trajectories. It does not shorten the catalog protocol or change its failed status."
    )
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results/catalog-paired-marhl-diagnostic")
    args = parser.parse_args()
    result = diagnose(args.output)
    print(json.dumps({k: result[k] for k in
                     ("all_full_horizon_comparisons_passed", "all_comparisons_through_normal_recall_passed")}, indent=2))
