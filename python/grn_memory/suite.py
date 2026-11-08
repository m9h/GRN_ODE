"""Run the selected published examples and save auditable results."""

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path

import numpy as np

from .experiments import (association_experiment, breaking_experiment,
                          repeated_experiment, retention_experiment)

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = {"retention": retention_experiment, "association": association_experiment,
             "repeated": repeated_experiment, "breaking": breaking_experiment}
CASES = {
    "no_memory": (31, "retention", ["Mp", "Mpp", -1]),
    "retained_response": (31, "retention", ["Mpp", "Mp", 1]),
    "associative_recall": (26, "association", ["M_MKP3", 1, "M", -1, "Mp_MAPKK"]),
    "drift_control": (26, "association", ["M_MKP3", -1, "Mp_MKP3_dep", -1, "Mpp"]),
    "transfer": (26, "association", ["Mp_MAPKK", 1, "M", 1, "M_MAPKK"]),
    "habituation": (10, "repeated", ["MKK", "MKK_PP", -1]),
    "sensitization": (27, "repeated", ["Mp", "Mpp", 1]),
    "breaking_habituation": (29, "breaking", ["MpT", "Mpp", -1, "M", 1]),
}


def compare(a, b, rtol=2e-5, atol=1e-7):
    """Mixed tolerance in each model's native concentration units."""
    if a.shape != b.shape or list(a.columns) != list(b.columns):
        raise ValueError("Incompatible trajectories")
    np.testing.assert_array_equal(a.phase, b.phase)
    np.testing.assert_allclose(a.time, b.time, rtol=0, atol=1e-9)
    x, y = (v.drop(columns=["time", "phase"]).to_numpy() for v in (a, b))
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Non-finite oracle result")
    error = np.abs(x-y)
    scaled = error/(atol+rtol*np.maximum(np.abs(x), np.abs(y)))
    return {"max_absolute_error": float(error.max()), "max_scaled_error": float(scaled.max()),
            "passed": bool((scaled <= 1).all())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=list(CASES), action="append")
    parser.add_argument("--engine", choices=["both", "roadrunner", "copasi"], default="both")
    parser.add_argument("--output", type=Path, default=ROOT / "results")
    parser.add_argument("--no-traces", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    engines = ["roadrunner", "copasi"] if args.engine == "both" else [args.engine]
    report = {"versions": {p: version(p) for p in ["libroadrunner", "copasi-basico", "python-copasi", "python-libsbml", "numpy"]},
              "solver_rtol": 1e-9, "solver_atol": 1e-11, "comparison_rtol": 2e-5,
              "comparison_atol": 1e-7, "dt": 0.01, "reset_interval": 0.1, "cases": {}}
    passed = True
    from .plotting import plot_case
    for name in args.case or CASES:
        number, kind, parameters = CASES[name]
        model = ROOT / "models" / f"BIOMD{number:010}.xml"
        entry = {"model": model.name, "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                 "kind": kind, "parameters": parameters, "scores": {}, "comparison": {}}
        outputs = {}
        for engine in engines:
            print(f"{name}: {engine}", flush=True)
            traces, score = FUNCTIONS[kind](model, *parameters, engine=engine)
            entry["scores"][engine] = score
            outputs[engine] = traces
            if not args.no_traces:
                for label, trace in traces.items():
                    trace.to_csv(args.output / f"{name}-{engine}-{label}.csv.gz", index=False,
                                 compression={"method": "gzip", "mtime": 0})
        if len(engines) == 2:
            entry["comparison"] = {label: compare(outputs["roadrunner"][label], outputs["copasi"][label])
                                   for label in outputs["roadrunner"]}
            passed &= all(item["passed"] for item in entry["comparison"].values())
            # Boolean conclusions are part of conformance, not just trajectories.
            entry["classification_agreement"] = all(
                entry["scores"]["copasi"][k] == v
                for k, v in entry["scores"]["roadrunner"].items() if isinstance(v, bool))
            passed &= entry["classification_agreement"]
        plot_case(name, kind, outputs[engines[0]], entry["scores"][engines[0]], args.output)
        report["cases"][name] = entry
    report["all_comparisons_passed"] = bool(passed) if len(engines) == 2 else None
    (args.output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(f"Saved {args.output / 'report.json'}", flush=True)
    if not passed:
        raise SystemExit("Simulator comparison failed; inspect report.json")


if __name__ == "__main__":
    main()
