"""Exhaustive single-input retention screen across the 35 BioModels.

This is the first stage of the catalog memory survey: every independently
writable state, both stimulation directions, and every other independent state
as a response. Association and repeated-stimulation protocols are separate
stages; this screen does not claim their completion or historical prevalence.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from .analysis import regulation, retained, retention_fraction
from .catalog_validation import ROOT, PACKAGES, comparison, inspect_model
from .native_protocols import ResetTrain, intervention_targets, protocol_trajectory, sample_times


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")
    temporary.replace(path)


def scores(trace, control, targets, stimulus, duration):
    """Keep paper-like retention distinct from time-matched retained effects."""
    def window(data, start, end, symbol):
        return data.loc[(data.time >= start) & (data.time <= end), symbol].to_numpy()
    result = {}
    for response in targets:
        if response == stimulus:
            continue
        b = window(trace, 0, duration, response)
        on = window(trace, duration, 2*duration, response)
        off = window(trace, 2*duration, 3*duration, response)
        on_control = window(control, duration, 2*duration, response)
        off_control = window(control, 2*duration, 3*duration, response)
        late = window(trace, 12*duration, 13*duration, response)
        late_control = window(control, 12*duration, 13*duration, response)
        direction = regulation(b, on, on_control)
        on_effect = float(on.mean()-on_control.mean())
        off_effect = float(off.mean()-off_control.mean())
        late_effect = float(late.mean()-late_control.mean())
        resolution = 2*(1e-7 + 2e-5*max(abs(on.mean()), abs(on_control.mean())))
        resolved = abs(on_effect) > resolution
        result[response] = {
            "response_direction": direction,
            "means": {"baseline": float(b.mean()), "train": float(on.mean()), "relax": float(off.mean()),
                      "train_control": float(on_control.mean()), "relax_control": float(off_control.mean()),
                      "late": float(late.mean()), "late_control": float(late_control.mean())},
            "paper_like_retained_fraction": retention_fraction(b, on, off),
            "paper_like_ucs_memory": bool(direction and retained(b, on, off, direction)),
            "training_effect_resolved": bool(resolved),
            "matched_retained_fraction": off_effect/on_effect if resolved else None,
            "matched_retention": (bool(direction and direction*off_effect >= .5*direction*on_effect)
                                  if resolved else None),
            "late_matched_retained_fraction": late_effect/on_effect if resolved else None,
        }
    return result


def classification_agreement(engine_scores, engines):
    """Expose raw label differences, but do not interpret unresolved effects.

Numerically tiny positive/negative tails can flip a fold threshold at zero.
Those labels are retained for audit, not accepted as physical memory evidence.
A disagreement involving a resolved effect remains a validation failure.
"""
    fields = ("response_direction", "paper_like_ucs_memory", "training_effect_resolved", "matched_retention")
    raw, resolved, unresolved = {}, {}, []
    a, b = (engine_scores[engine] for engine in engines)
    for response in a:
        differences = [field for field in fields if a[response][field] != b[response][field]]
        if differences:
            raw[response] = differences
        if not a[response]["training_effect_resolved"] and not b[response]["training_effect_resolved"]:
            unresolved.append(response)
        elif differences:
            resolved[response] = differences
    return raw, resolved, unresolved


def run_model(entry, args):
    path = ROOT / "models" / f'{entry["biomodel_id"]}.xml'
    info = inspect_model(path)
    targets, excluded = intervention_targets(path)
    # Checked against independent trajectories at the same acceptance tolerance.
    # Marhl's late oscillatory phase needs tighter integration.
    defaults = {30: (1e-13, 1e-15)}
    default_rtol, default_atol = defaults.get(entry["network"], (1e-12, 1e-14))
    rtol = args.rtol if args.rtol is not None else default_rtol
    atol = args.atol if args.atol is not None else default_atol
    delay = bool(info["delay_expressions"])
    if delay:
        from .delay_protocols import delay_protocol_trajectory as trajectory
        engines = ["scipy-method-of-steps", "jitcdde"]
    else:
        trajectory = protocol_trajectory
        engines = ["roadrunner", "copasi"]
    integration = {engine: {"rtol": rtol, "atol": atol} for engine in engines}
    if entry["network"] == 35:
        # LSODA step-limit failures occur at tighter requests on stiff reset
        # transients. Keep CVODE tight and compare all samples at the unchanged
        # acceptance threshold; the less demanding LSODA request is recorded.
        integration["copasi"] = {"rtol": args.rtol if args.rtol is not None else 1e-8,
                                 "atol": args.atol if args.atol is not None else 1e-10}
    files = ["catalog_memory.py", "native_protocols.py", "delay_protocols.py", "scheper_delay.py",
             "catalog_validation.py", "analysis.py", "simulation.py"]
    config = {"duration": args.duration, "dt": args.dt, "reset_interval": .1, "post_reset_offset": 1e-6,
              "solver_rtol": rtol, "solver_atol": atol, "comparison_rtol": 2e-5,
              "comparison_atol": 1e-7, "input_scale_up": 100., "input_scale_down": .01,
              "calibration": "original initial state, native time 0 through duration",
              "phases": {"baseline": [0,1], "train": [1,2], "relax": [2,3], "long_relax": [3,13]},
              "phase_units": "multiples of duration", "limit_inputs": args.limit_inputs,
              "zero_baseline_policy": "run and report as degenerate; do not invent a nonzero stimulus",
              "negative_minimum_policy": "round to zero only within 100 solver absolute tolerances"}
    config["integration_settings"] = integration
    config["copasi_intervention_method"] = "not applicable: DDE" if delay else "native SBML events"
    config["resets_per_training"] = len(ResetTrain(args.duration, 2*args.duration, {}).indices())
    versions = {p: version(p) for p in PACKAGES}
    if delay:
        versions.update({p: version(p) for p in ("scipy", "jitcdde", "symengine")})
        config.update({"jitcdde_step": .001, "jitcdde_refined_step": .0005,
                       "jump_width": 1e-9, "refined_jump_width": 5e-10,
                       "history": "M=P=1 for t<0; preserve solved history across resets"})
    provenance = {"model_sha256": info["sha256"], "configuration": config, "versions": versions,
                  "implementation_sha256": {name: hashlib.sha256((ROOT/"grn_memory"/name).read_bytes()).hexdigest()
                                             for name in files}}
    fingerprint = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
    destination = args.output / f'{entry["biomodel_id"]}.json'
    report = {**entry, "name": info["name"], **provenance, "fingerprint": fingerprint, "engines": engines,
              "targets": targets, "excluded_species": excluded, "expected_cases": 2*len(targets),
              "cases": {}, "status": "running", "started_at": datetime.now(timezone.utc).isoformat()}
    if destination.exists() and args.resume:
        previous = json.loads(destination.read_text())
        if previous.get("fingerprint") == fingerprint:
            report = previous
    write_json(destination, report)
    # All single-input cases share one reset schedule and therefore one sample
    # grid. The untreated control uses that grid too, for exact time matching.
    grid_train = ResetTrain(args.duration, 2*args.duration, {})
    times = sample_times(13*args.duration, args.dt, [grid_train])
    control = {engine: trajectory(path, times, [], engine, **integration[engine])
               for engine in engines}
    report["control_comparison"] = comparison(*control.values())
    baseline = control[engines[0]].loc[control[engines[0]].time <= args.duration]
    selected = list(targets)[:args.limit_inputs] if args.limit_inputs else list(targets)
    for symbol in selected:
        minimum, maximum = float(baseline[symbol].min()), float(baseline[symbol].max())
        for direction in (1, -1):
            key = symbol + ("__up" if direction == 1 else "__down")
            if args.resume and key in report["cases"] and report["cases"][key]["status"] == "passed":
                continue
            start = time.monotonic()
            case = {"input": symbol, "direction": direction, "status": "failed",
                    "baseline_minimum": minimum, "baseline_maximum": maximum,
                    "degenerate_zero_baseline": maximum == 0 and minimum == 0}
            try:
                if minimum < -100*atol:
                    raise ValueError("Negative baseline exceeds declared numerical-roundoff allowance")
                level = max(0., maximum)*100 if direction == 1 else max(0., minimum)/100
                case["level"] = level
                train = ResetTrain(args.duration, 2*args.duration, {symbol: level})
                traces = {engine: trajectory(path, times, [train], engine, **integration[engine])
                          for engine in engines}
                case["comparison"] = comparison(*traces.values())
                case["scores"] = {engine: scores(trace, control[engine], targets, symbol, args.duration)
                                  for engine, trace in traces.items()}
                raw, resolved, unresolved = classification_agreement(case["scores"], engines)
                case["classification_disagreements"] = raw
                case["resolved_classification_disagreements"] = resolved
                case["unresolved_responses"] = unresolved
                passed = case["comparison"]["passed"] and not resolved
                if delay:
                    refined = trajectory(path, times, [train], "jitcdde", step=.0005, jump_width=5e-10)
                    case["refinement"] = {"versus_method_of_steps": comparison(traces[engines[0]], refined),
                                          "versus_original_step": comparison(traces[engines[1]], refined)}
                    passed = passed and all(c["passed"] for c in case["refinement"].values())
                case["status"] = "passed" if passed else "mismatch"
                if args.traces:
                    for engine, trace in traces.items():
                        trace.to_csv(args.output/f'{entry["biomodel_id"]}-{key}-{engine}.csv.gz', index=False)
            except Exception as exc:
                case["error"] = f"{type(exc).__name__}: {exc}"
            case["elapsed_seconds"] = time.monotonic()-start
            report["cases"][key] = case
            write_json(destination, report)
            print(f'{entry["network"]:02d} {key}: {case["status"]} {case.get("error", "")}', flush=True)
    report["evaluated_cases"] = len(report["cases"])
    report["passed_cases"] = sum(c["status"] == "passed" for c in report["cases"].values())
    report["status"] = ("passed" if report["passed_cases"] == report["expected_cases"]
                        and report["control_comparison"]["passed"] else "incomplete_or_failed")
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(destination, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"results/catalog-memory")
    parser.add_argument("--network", action="append", type=int)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--duration", type=float, default=50)
    parser.add_argument("--dt", type=float, default=.01)
    parser.add_argument("--rtol", type=float, help="Override documented per-model integration tolerance")
    parser.add_argument("--atol", type=float, help="Override documented per-model integration tolerance")
    parser.add_argument("--limit-inputs", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--traces", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if min(args.workers, args.timeout, args.duration, args.dt) <= 0 or any(
            value is not None and (not np.isfinite(value) or value <= 0) for value in (args.rtol, args.atol)):
        parser.error("Counts, times and tolerances must be positive")
    if args.limit_inputs is not None and args.limit_inputs < 1:
        parser.error("limit-inputs must be positive")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    catalog = json.loads((ROOT/"models/catalog.json").read_text())["models"]
    if args.network:
        if set(args.network)-{entry["network"] for entry in catalog}:
            parser.error("Unknown catalog network")
        catalog = [entry for entry in catalog if entry["network"] in args.network]
    manifest = {r["file"]: r["sha256"] for r in json.loads((ROOT/"models/manifest.json").read_text())}
    for entry in catalog:
        path = ROOT/"models"/f'{entry["biomodel_id"]}.xml'
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest[path.name]:
            raise ValueError(f"Source model hash changed: {path}")
    if args.worker:
        if len(catalog) != 1:
            parser.error("Worker requires exactly one model")
        result = run_model(catalog[0], args)
        raise SystemExit(0 if result["status"] == "passed" else 1)
    def isolated(entry):
        command = [sys.executable, "-m", "grn_memory.catalog_memory", "--worker", "--network", str(entry["network"]),
                   "--output", str(args.output), "--duration", str(args.duration), "--dt", str(args.dt)]
        for name in ("rtol", "atol"):
            if getattr(args, name) is not None:
                command.extend(["--"+name, str(getattr(args, name))])
        for flag in ("resume", "traces"):
            if getattr(args, flag):
                command.append("--"+flag)
        if args.limit_inputs:
            command.extend(["--limit-inputs", str(args.limit_inputs)])
        env = dict(os.environ)
        env.setdefault("MPLCONFIGDIR", str(args.output/".mpl-cache"))
        with (args.output/f'{entry["biomodel_id"]}.log').open("w") as stream:
            try:
                process = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, env=env, timeout=args.timeout)
                worker = {"returncode": process.returncode}
            except subprocess.TimeoutExpired:
                worker = {"timeout": args.timeout}
        destination = args.output/f'{entry["biomodel_id"]}.json'
        result = json.loads(destination.read_text()) if destination.exists() else {**entry, "status": "failed"}
        if worker.get("returncode") != 0:
            result["status"] = "incomplete_or_failed"
        return {**result, "worker": worker}
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(isolated, entry) for entry in catalog]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f'{result["network"]:02d} {result["status"]}: {result.get("passed_cases",0)}/{result.get("expected_cases",0)} cases', flush=True)
    report = {"scope": "Exhaustive single-input retention screen; association and repeated stimulation remain separate stages",
              "model_count": len(results), "passed_models": sum(r["status"] == "passed" for r in results),
              "models": sorted(results, key=lambda r:r["network"])}
    write_json(args.output/"report.json", report)
    if report["passed_models"] != report["model_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
