"""Validate original model kinetics for all 35 Table S1 models.

This baseline layer preserves native events, assignment/rate rules and time.
It is separate from the existing autonomous concentration-reset experiments.
Every species and every rule/event target is observed, including parameters
that are dynamical state variables rather than reaction species.
The Scheper delay model uses a separately validated, model-specific DDE adapter.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import libsbml
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("libroadrunner", "python-copasi", "copasi-basico", "python-libsbml", "numpy")


def inspect_model(path):
    doc = libsbml.readSBML(str(path))
    if doc.getNumErrors(libsbml.LIBSBML_SEV_ERROR) or doc.getModel() is None:
        raise ValueError(doc.getErrorLog().toString())
    model = doc.getModel()
    species = [s.getId() for s in model.getListOfSpecies()]
    rules = [{"target": r.getVariable(), "type": "assignment" if r.isAssignment()
              else "rate" if r.isRate() else "algebraic",
              "formula": libsbml.formulaToL3String(r.getMath())}
             for r in model.getListOfRules()]
    events = [{"id": e.getId(), "trigger": libsbml.formulaToL3String(e.getTrigger().getMath()),
               "assignments": {a.getVariable(): libsbml.formulaToL3String(a.getMath())
                               for a in e.getListOfEventAssignments()}}
              for e in model.getListOfEvents()]
    targets = [r["target"] for r in rules if r["target"]]
    targets += [key for e in events for key in e["assignments"]]
    delays = []
    def find_delays(ast):
        if ast is None:
            return
        if ast.getType() == libsbml.AST_FUNCTION_DELAY:
            delays.append(libsbml.formulaToL3String(ast))
        for i in range(ast.getNumChildren()):
            find_delays(ast.getChild(i))
    for expression in [r.getKineticLaw().getMath() for r in model.getListOfReactions()] + [
            r.getMath() for r in model.getListOfRules()] + [f.getMath() for f in model.getListOfFunctionDefinitions()]:
        find_delays(expression)
    observables = list(dict.fromkeys(species + targets))
    types = {s: "concentration" for s in species}
    types.update({s: "parameter" if model.getParameter(s) else "compartment"
                  for s in observables if s not in species})
    from .simulation import model_info
    try:
        _, independent = model_info(path)
        current_protocol = {"supported": True, "independent_species": independent}
    except ValueError as exc:
        current_protocol = {"supported": False, "reason": str(exc)}
    return {
        "name": model.getName(), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "species": species, "observables": observables, "observable_types": types,
        "reaction_count": model.getNumReactions(), "rules": rules, "events": events,
        "delay_expressions": delays,
        "initial_assignment_count": model.getNumInitialAssignments(),
        "existing_reset_protocol": current_protocol,
    }


def native_trajectory(path, times, engine, *, rtol=1e-10, atol=1e-12):
    info = inspect_model(path)
    columns = info["observables"]
    if engine == "roadrunner":
        import roadrunner
        model = roadrunner.RoadRunner(str(path))
        model.conservedMoietyAnalysis = False
        model.integrator.relative_tolerance = rtol
        model.integrator.absolute_tolerance = atol
        model.integrator.maximum_num_steps = 100000
        selection = [f"[{s}]" if info["observable_types"][s] == "concentration" else s
                     for s in columns]
        values = np.asarray(model.simulate(times=list(times), selections=["time"] + selection))
    elif engine == "copasi":
        import basico
        import COPASI
        data = basico.load_model(str(path))
        if data is None:
            raise ValueError(f"COPASI could not import {path}")
        try:
            model = data.getModel()
            references = {s.getSBMLId(): s.getConcentrationReference()
                          for s in model.getMetabolites()}
            references.update({p.getSBMLId(): p.getValueReference() for p in model.getModelValues()})
            references.update({c.getSBMLId(): c.getValueReference() for c in model.getCompartments()})
            cns = ["Time"]
            cns += [references[s].getCN().getString() for s in columns]
            output = basico.run_time_course_with_output(
                cns, model=data, values=list(times), use_initial_values=True,
                method="deterministic", automatic=False, output_event=False,
                r_tol=rtol, a_tol=atol, max_steps=100000,
            )
            values = output.to_numpy()
        finally:
            COPASI.CRootContainer.removeDatamodel(data)
    else:
        raise ValueError(f"Unknown native engine {engine}")
    if values.shape != (len(times), len(columns) + 1):
        raise ValueError(f"Unexpected output shape {values.shape}")
    np.testing.assert_allclose(values[:, 0], times, rtol=0, atol=1e-9)
    if not np.isfinite(values).all():
        raise ValueError("Non-finite native trajectory")
    return pd.DataFrame(values, columns=["time"] + columns)


def comparison(a, b, *, rtol=2e-5, atol=1e-7):
    if list(a.columns) != list(b.columns) or a.shape != b.shape:
        raise ValueError("Incompatible native trajectories")
    np.testing.assert_allclose(a.time, b.time, rtol=0, atol=1e-9)
    x, y = a.iloc[:, 1:].to_numpy(), b.iloc[:, 1:].to_numpy()
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Non-finite comparison")
    absolute = np.abs(x-y)
    scaled = absolute / (atol + rtol * np.maximum(np.abs(x), np.abs(y)))
    row, col = np.unravel_index(np.argmax(scaled), scaled.shape)
    return {"passed": bool(np.all(scaled <= 1)), "max_scaled_error": float(scaled.max()),
            "max_absolute_error": float(absolute.max()), "worst_observable": a.columns[col+1],
            "worst_time": float(a.time.iloc[row]), "samples": len(a),
            "observables": len(a.columns)-1,
            "per_observable_max_scaled_error": dict(zip(a.columns[1:], scaled.max(axis=0).tolist()))}


def run_model(entry, output, duration, dt, rtol, atol):
    start = time.monotonic()
    path = ROOT / "models" / f'{entry["biomodel_id"]}.xml'
    info = inspect_model(path)
    result = {**entry, **info, "status": "failed", "versions": {p: version(p) for p in PACKAGES},
              "recorded_at": datetime.now(timezone.utc).isoformat(),
              "implementation_sha256": {name: hashlib.sha256((ROOT / "grn_memory" / name).read_bytes()).hexdigest()
                                         for name in ("catalog_validation.py", "scheper_delay.py", "simulation.py")},
              "configuration": {"duration": duration, "dt": dt, "solver_rtol": rtol,
                                "solver_atol": atol, "comparison_rtol": 2e-5,
                                "comparison_atol": 1e-7, "native_sbml_unchanged": True}}
    n = round(duration / dt)
    if duration <= 0 or dt <= 0 or not np.isclose(n*dt, duration):
        raise ValueError("duration must be a positive multiple of dt")
    times = np.linspace(0, duration, n+1)
    try:
        trajectories = {}
        if info["delay_expressions"]:
            from .scheper_delay import trajectory
            engines = ("scipy-method-of-steps", "jitcdde")
            result["versions"].update({p: version(p) for p in ("scipy", "jitcdde", "symengine")})
            result["configuration"].update({"adapter": "scheper_delay", "delay": 4.0,
                "history": "constant initial concentrations for t <= 0: M=1, P=1",
                "jitcdde_step": .001, "jitcdde_refined_step": .0005,
                "initial_discontinuity_step": 1e-10})
            result["native_engine_limitations"] = {
                "roadrunner": "Rejects delay(M, tau); no native DDE support",
                "copasi": "Native delay import fails during the deterministic time course"}
        else:
            trajectory = native_trajectory
            engines = ("roadrunner", "copasi")
        result["engines"] = list(engines)
        for engine in engines:
            trace = trajectory(path, times, engine, rtol=rtol, atol=atol)
            trajectories[engine] = trace
            trace.to_csv(output / f'{entry["biomodel_id"]}-{engine}.csv.gz', index=False,
                         compression={"method": "gzip", "mtime": 0})
        result["comparison"] = comparison(trajectories[engines[0]], trajectories[engines[1]])
        result["initial_values"] = trajectories[engines[0]].iloc[0].drop("time").to_dict()
        result["final_values"] = trajectories[engines[0]].iloc[-1].drop("time").to_dict()
        result["status"] = "passed" if result["comparison"]["passed"] else "mismatch"
        if info["delay_expressions"]:
            refined = trajectory(path, times, "jitcdde", step=.0005)
            result["refinement"] = {
                "versus_method_of_steps": comparison(trajectories[engines[0]], refined),
                "versus_original_step": comparison(trajectories[engines[1]], refined)}
            if not all(v["passed"] for v in result["refinement"].values()):
                result["status"] = "mismatch"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["elapsed_seconds"] = time.monotonic()-start
    destination = output / f'{entry["biomodel_id"]}.json'
    destination.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results/catalog")
    parser.add_argument("--network", type=int, action="append")
    parser.add_argument("--duration", type=float, default=50)
    parser.add_argument("--dt", type=float, default=.01)
    parser.add_argument("--rtol", type=float, default=1e-10)
    parser.add_argument("--atol", type=float, default=1e-12)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.workers < 1 or args.timeout <= 0:
        parser.error("workers and timeout must be positive")
    if args.duration <= 0 or args.dt <= 0 or args.rtol <= 0 or args.atol <= 0:
        parser.error("duration, dt and tolerances must be positive")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    catalog = json.loads((ROOT / "models/catalog.json").read_text())["models"]
    manifest = {r["file"]: r for r in json.loads((ROOT / "models/manifest.json").read_text())}
    if args.network:
        if set(args.network)-{e["network"] for e in catalog}:
            parser.error("Unknown catalog network")
        catalog = [e for e in catalog if e["network"] in args.network]
    for entry in catalog:
        path = ROOT / "models" / f'{entry["biomodel_id"]}.xml'
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest[path.name]["sha256"]:
            raise ValueError(f"Model hash mismatch: {path}")
    if args.worker:
        if len(catalog) != 1:
            parser.error("Worker requires one model")
        result = run_model(catalog[0], args.output, args.duration, args.dt, args.rtol, args.atol)
        raise SystemExit(0 if result["status"] == "passed" else 1)

    def isolated(entry):
        command = [sys.executable, "-m", "grn_memory.catalog_validation", "--worker",
                   "--network", str(entry["network"]), "--output", str(args.output),
                   "--duration", str(args.duration), "--dt", str(args.dt),
                   "--rtol", str(args.rtol), "--atol", str(args.atol)]
        log = args.output / f'{entry["biomodel_id"]}.log'
        destination = args.output / f'{entry["biomodel_id"]}.json'
        # A stale report must never stand in for a failed new worker.
        if destination.exists():
            destination.unlink()
        env = dict(os.environ)
        env.setdefault("MPLCONFIGDIR", str(args.output / ".mpl-cache"))
        error = None
        with log.open("w") as stream:
            try:
                proc = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                      timeout=args.timeout, env=env)
                if proc.returncode:
                    error = f"Worker exited {proc.returncode}; see {log.name}"
            except subprocess.TimeoutExpired:
                error = f"Worker exceeded {args.timeout} seconds; see {log.name}"
        if destination.exists():
            result = json.loads(destination.read_text())
        else:
            result = {**entry, "status": "failed", "error": error or "Worker did not write a report"}
            destination.write_text(json.dumps(result, indent=2) + "\n")
        return result

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(isolated, catalog):
            results.append(result)
            message = result.get("error") or str(result.get("comparison", {}).get("max_scaled_error", ""))
            print(f'{result["network"]:02d} {result["biomodel_id"]}: {result["status"]} {message}', flush=True)
    report = {"scope": "Original model baselines, with a model-specific adapter for the Scheper DDE; not a memory prevalence survey",
              "model_count": len(results), "passed": sum(r["status"] == "passed" for r in results),
              "models": results}
    (args.output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    if report["passed"] != report["model_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
