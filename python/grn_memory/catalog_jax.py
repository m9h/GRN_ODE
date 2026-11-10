"""Audit Jaxkineticmodel against both native engines for every catalog baseline.

Unsupported imports are recorded separately from numerical failures, and never
count as validated models. Species defined by assignment rules are reconstructed
as observables; they are not extra independent ODE states.
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
import pandas as pd

from .catalog_memory import write_json
from .catalog_validation import ROOT, PACKAGES, comparison, inspect_model, native_trajectory
from .native_protocols import intervention_targets


def source_hashes():
    import jaxkineticmodel.load_sbml as package
    root = Path(package.__file__).parent
    result = {"jaxkineticmodel/load_sbml/"+name: hashlib.sha256((root/name).read_bytes()).hexdigest()
              for name in ("sbml_model.py", "jax_kinetic_model.py", "sympy_converter.py", "export_sbml.py",
                           "sbml_load_utils.py")}
    result.update({"grn_memory/"+name: hashlib.sha256((ROOT/"grn_memory"/name).read_bytes()).hexdigest()
                   for name in ("catalog_jax.py", "catalog_validation.py", "native_protocols.py")})
    return result


def observable_trajectory(model, solve, times, states, observable_names):
    """Evaluate native SBML symbols, then convert species amounts to concentrations."""
    import sympy
    symbols = {**model.parameters, **model.compartments, **model.boundary_conditions,
               **dict(zip(model.species_names, np.asarray(states).T)), "t": np.asarray(times)}
    for target, expression in solve.resolved_assignment_rules.items():
        arguments = sorted(expression.free_symbols, key=str)
        evaluate = sympy.lambdify(arguments, expression, "numpy")
        symbols[str(target)] = evaluate(*[symbols[str(s)] for s in arguments])
    columns = {"time": np.asarray(times)}
    for name in observable_names:
        value = np.broadcast_to(symbols[name], (len(times),)).astype(float)
        if name in model.amount_species:
            compartment = model.model.getSpecies(name).getCompartment()
            value = value/model.compartments[compartment]
        columns[name] = value
    result = pd.DataFrame(columns)
    if not np.isfinite(result.to_numpy()).all():
        raise ValueError("Non-finite JAX observable trajectory")
    return result


def run_model(entry, args):
    import jax
    import jax.numpy as jnp
    import diffrax
    from jaxkineticmodel.load_sbml.sbml_model import SBMLModel

    path = ROOT/"models"/f'{entry["biomodel_id"]}.xml'
    info = inspect_model(path)
    config = {"duration": 50., "dt": .01, "jax_solver": "Kvaerno5", "jax_rtol": 1e-10,
              "jax_atol": 1e-12, "reference_rtol": 1e-12, "reference_atol": 1e-14, "jax_initial_step": 1e-4,
              "comparison_rtol": 2e-5, "comparison_atol": 1e-7, "x64": bool(jax.config.x64_enabled)}
    if entry["network"] == 29:
        config["jax_solver"] = "Tsit5"
    if entry["network"] == 35:
        config.update(jax_rtol=1e-7, jax_atol=1e-9)
    metadata = {"model_sha256": info["sha256"], "configuration": config,
                "implementation_sha256": source_hashes(),
                "versions": {p: version(p) for p in (*PACKAGES, "jax", "jaxlib", "diffrax", "equinox", "jaxkineticmodel")}}
    fingerprint = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    destination = args.output/f'{entry["biomodel_id"]}.json'
    if args.resume and destination.exists():
        saved = json.loads(destination.read_text())
        if saved.get("fingerprint") == fingerprint and saved["status"] in {"passed", "unsupported"}:
            return saved
    report = {**entry, **metadata, "fingerprint": fingerprint, "name": info["name"], "status": "running",
              "observables": info["observables"], "recorded_at": datetime.now(timezone.utc).isoformat()}
    write_json(destination, report)
    started = time.monotonic()
    try:
        try:
            model = SBMLModel(str(path))
            solve = model.get_kinetic_model()
        except NotImplementedError as exc:
            report.update(status="unsupported", reason=str(exc))
            return report
        expected, _ = intervention_targets(path)
        if model.species_names != list(expected) or len(model.y0) != len(expected):
            raise ValueError("JAX independent state inventory does not match the SBML catalog")
        report["independent_states"] = model.species_names
        solve.dt0 = config["jax_initial_step"]
        solver = getattr(diffrax, config["jax_solver"])()
        solve._change_solver(solver, rtol=config["jax_rtol"], atol=config["jax_atol"])
        times = np.linspace(0, 50, 5001)
        values = jax.jit(solve)(jnp.asarray(times), model.y0, model.parameters)
        traces = {"jaxkineticmodel": observable_trajectory(model, solve, times, values, info["observables"])}
        for engine in ("roadrunner", "copasi"):
            traces[engine] = native_trajectory(path, times, engine,
                rtol=config["reference_rtol"], atol=config["reference_atol"])
        report["comparisons"] = {"jax_roadrunner": comparison(traces["jaxkineticmodel"], traces["roadrunner"]),
                                 "jax_copasi": comparison(traces["jaxkineticmodel"], traces["copasi"]),
                                 "roadrunner_copasi": comparison(traces["roadrunner"], traces["copasi"])}
        report["status"] = "passed" if all(c["passed"] for c in report["comparisons"].values()) else "mismatch"
        report["initial_values"] = traces["jaxkineticmodel"].iloc[0].drop("time").to_dict()
        report["final_values"] = traces["jaxkineticmodel"].iloc[-1].drop("time").to_dict()
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        report["elapsed_seconds"] = time.monotonic()-started
        write_json(destination, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"results/catalog-jax")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--network", type=int, action="append")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--expect-unsupported", type=int, action="append", default=[],
                        help="Require exactly these unsupported networks for a coverage gate; they never count as validated")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.workers < 1 or args.timeout <= 0:
        parser.error("Workers and timeout must be positive")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    catalog = json.loads((ROOT/"models/catalog.json").read_text())["models"]
    if args.network:
        if set(args.network)-{e["network"] for e in catalog}:
            parser.error("Unknown network")
        catalog = [e for e in catalog if e["network"] in args.network]
    if args.worker:
        if len(catalog) != 1:
            parser.error("Worker requires one network")
        result = run_model(catalog[0], args)
        raise SystemExit(0 if result["status"] in {"passed", "unsupported"} else 1)

    def isolated(entry):
        command = [sys.executable, "-m", "grn_memory.catalog_jax", "--worker", "--network", str(entry["network"]),
                   "--output", str(args.output)]
        if args.resume:
            command.append("--resume")
        env = {**os.environ, "JAX_PLATFORMS": "cpu", "OMP_NUM_THREADS": "1"}
        with (args.output/f'{entry["biomodel_id"]}.log').open("w") as stream:
            try:
                execution = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, env=env, timeout=args.timeout)
                worker = {"returncode": execution.returncode}
            except subprocess.TimeoutExpired:
                worker = {"timeout": args.timeout}
        destination = args.output/f'{entry["biomodel_id"]}.json'
        record = json.loads(destination.read_text()) if destination.exists() else {**entry, "status": "failed"}
        if worker.get("returncode") != 0:
            record["status"] = "failed"
        return {**record, "worker": worker}

    records = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(isolated, entry) for entry in catalog]):
            record = future.result()
            records.append(record)
            reason = record.get("reason", record.get("error", ""))
            if "maximum number of solver steps" in reason:
                reason = "Maximum number of solver steps reached (full error in model report)"
            print(f'{record["network"]:02d}: {record["status"]} {reason}', flush=True)
    report = {"model_count": len(records), "validated_models": sum(r["status"] == "passed" for r in records),
              "unsupported_models": sum(r["status"] == "unsupported" for r in records),
              "models": sorted(records, key=lambda r:r["network"])}
    report["all_models_validated"] = report["validated_models"] == len(records)
    unsupported = {r["network"] for r in records if r["status"] == "unsupported"}
    report["expected_unsupported"] = sorted(set(args.expect_unsupported))
    report["expected_coverage_satisfied"] = (
        unsupported == set(args.expect_unsupported)
        and report["validated_models"] + len(unsupported) == len(records))
    write_json(args.output/"report.json", report)
    if not report["expected_coverage_satisfied"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
