"""JAX reference trajectories with complete state carried through external resets.

This adapter supports autonomous reaction models with fixed positive-volume
compartments and assignment-rule observables. Native events, delay/rate/algebraic
rules, initial assignments and conversion factors are explicitly unsupported.
All integration intervals retain absolute SBML time. Requested samples must
avoid reset instants, as in the native catalog's offset observation grid.
"""

from functools import lru_cache
import hashlib
from pathlib import Path

import libsbml
import numpy as np

from .catalog_jax import observable_trajectory
from .catalog_validation import inspect_model
from .native_protocols import encode_protocol, intervention_targets


def supported_model(path):
    """Fail before integration when the adapter cannot preserve SBML semantics."""
    info = inspect_model(path)
    if info["events"]:
        raise NotImplementedError("Native events need the native protocol adapter")
    if info["delay_expressions"]:
        raise NotImplementedError("Delay expressions need a history-preserving adapter")
    if any(r["type"] != "assignment" for r in info["rules"]):
        raise NotImplementedError("Rate and algebraic rules are unsupported by this JAX adapter")
    if info["initial_assignment_count"]:
        raise NotImplementedError("Initial assignments are not validated for this JAX adapter")
    doc = libsbml.readSBML(str(path))
    model = doc.getModel()
    assigned = {r["target"] for r in info["rules"]}
    for c in model.getListOfCompartments():
        if (not c.getConstant() or c.getId() in assigned or not np.isfinite(c.getSize())
                or c.getSize() <= 0 or c.getSpatialDimensions() == 0):
            raise NotImplementedError("Fixed positive-volume compartments are required")
    if model.isSetConversionFactor() or any(s.isSetConversionFactor() for s in model.getListOfSpecies()):
        raise NotImplementedError("SBML conversion factors are not supported")

    def uses_time(ast):
        return ast is not None and (ast.getType() == libsbml.AST_NAME_TIME or
            any(uses_time(ast.getChild(i)) for i in range(ast.getNumChildren())))

    expressions = [r.getKineticLaw().getMath() for r in model.getListOfReactions()]
    expressions += [r.getMath() for r in model.getListOfRules()]
    expressions += [f.getMath() for f in model.getListOfFunctionDefinitions()]
    if any(uses_time(ast) for ast in expressions):
        raise NotImplementedError("Time-dependent expressions require a separately validated drive policy")
    return info


@lru_cache(maxsize=8)
def _compiled(path, sha256, rtol, atol, solver):
    import diffrax
    import jax
    import jax.numpy as jnp
    from jaxkineticmodel.load_sbml.sbml_model import SBMLModel

    info = supported_model(path)
    if info["sha256"] != sha256:
        raise ValueError("SBML source changed while preparing JAX integration")
    model = SBMLModel(path)
    ode = model.get_kinetic_model()
    if not jax.config.x64_enabled:
        raise ValueError("JAX 64-bit arithmetic is required")
    targets, _ = intervention_targets(path)
    if model.species_names != list(targets) or len(model.y0) != len(targets) or not targets:
        raise ValueError("JAX independent state inventory differs from SBML")
    ode.dt0 = 1e-4
    ode._change_solver(getattr(diffrax, solver)(), rtol=rtol, atol=atol)
    solve = jax.jit(lambda times, state: ode(times, state, model.parameters))
    factors = np.array([model.compartments[model.model.getSpecies(s).getCompartment()]
                        if s in model.amount_species else 1. for s in model.species_names])
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != sha256:
        raise ValueError("SBML source changed while preparing JAX integration")
    return model, ode, solve, factors, info["observables"], jnp.asarray


def jax_protocol_trajectory(path, times, trains, *, rtol=1e-10, atol=1e-12,
                            solver="Kvaerno5", evidence=None):
    """Integrate all requested observables; never return an incomplete trajectory.

The optional evidence dictionary records reset and segment counts, including
the last attempted interval on failure. Source hashes participate in the compile
cache key, so replacing an XML file cannot reuse a stale compiled model.
"""
    path = Path(path).resolve()
    times = np.asarray(times, dtype=float)
    trains = tuple(trains)
    if (times.ndim != 1 or len(times) < 2 or not np.isfinite(times).all()
            or times[0] != 0 or np.any(np.diff(times) <= 0)):
        raise ValueError("Finite increasing sample times must start at zero")
    if not np.isfinite([rtol, atol]).all() or min(rtol, atol) <= 0:
        raise ValueError("Positive finite solver tolerances are required")
    if solver not in ("Kvaerno3", "Kvaerno4", "Kvaerno5"):
        raise ValueError("Choose Kvaerno3, Kvaerno4 or Kvaerno5")
    if any(t.stop > times[-1] for t in trains):
        raise ValueError("Reset train extends beyond the simulation window")
    supported_model(path)
    # Reuse the native adapter's target, value, endpoint and conflict validation.
    encode_protocol(path, trains)
    events = {}
    for i, train in enumerate(trains):
        if not train.values:
            continue
        for when in train.times():
            event = events.setdefault(float(when), {"values": {}, "trains": []})
            event["values"].update(train.values)
            event["trains"].append(i)
    resets = np.array(sorted(events))
    if len(resets):
        if resets[0] <= 0 or resets[-1] >= times[-1]:
            raise ValueError("Every reset must be strictly inside the observation window")
        if np.any(np.diff(resets) <= 1e-10):
            raise ValueError("Near-coincident resets need an explicit ordering policy")
        locations = np.searchsorted(times, resets)
        distance = np.minimum(np.abs(times[locations]-resets), np.abs(times[locations-1]-resets))
        if np.any(distance <= 1e-10):
            raise ValueError("Sample just before or after resets, not at an ambiguous reset instant")
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    model, ode, solve, factors, observables, asarray = _compiled(str(path), source_hash, rtol, atol, solver)
    indices = {s: i for i, s in enumerate(model.species_names)}
    state = np.asarray(model.y0).copy()
    states = np.full((len(times), len(state)), np.nan)
    edges = np.r_[0., resets, times[-1]]
    evidence = {} if evidence is None else evidence
    evidence.update(model_sha256=source_hash, solver=solver, rtol=rtol, atol=atol,
        x64=True, initial_step=1e-4, maximum_steps_per_interval=ode.max_steps,
        absolute_time_preserved=True, expected_resets=len(resets), performed_resets=0,
        expected_train_reset_counts=[len(t.indices()) if t.values else 0 for t in trains],
        train_reset_counts=[0]*len(trains), completed_segments=0, expected_segments=len(edges)-1,
        completed=False, sample_count=len(times))
    for start, end in zip(edges[:-1], edges[1:]):
        evidence["last_interval"] = [float(start), float(end)]
        if start in events:
            for symbol, value in events[start]["values"].items():
                state[indices[symbol]] = value*factors[indices[symbol]]
            evidence["performed_resets"] += 1
            for i in events[start]["trains"]:
                evidence["train_reset_counts"][i] += 1
        first = np.searchsorted(times, start)
        last = np.searchsorted(times, end, side="right" if end == times[-1] else "left")
        requested = times[first:last]
        segment_times = np.unique(np.r_[start, requested, end])
        try:
            values = np.asarray(solve(asarray(segment_times), asarray(state)))
            if values.shape != (len(segment_times), len(state)) or not np.isfinite(values).all():
                raise ValueError("Incomplete or non-finite JAX segment")
        except Exception as exc:
            raise RuntimeError(f"JAX integration failed on [{start}, {end}]: {exc}") from exc
        states[first:last] = values[np.searchsorted(segment_times, requested)]
        state = values[-1].copy()
        evidence["completed_segments"] += 1
    if (not np.isfinite(states).all() or evidence["performed_resets"] != len(resets)
            or evidence["train_reset_counts"] != evidence["expected_train_reset_counts"]):
        raise RuntimeError("JAX protocol did not complete every sample and scheduled reset")
    result = observable_trajectory(model, ode, times, states, observables)
    evidence["completed"] = True
    return result
