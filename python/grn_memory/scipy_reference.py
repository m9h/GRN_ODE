"""Independent stiff integration of the Jaxkineticmodel equations with SciPy.

JAX supplies the right-hand side and its automatic-differentiation Jacobian;
SciPy supplies Radau or BDF integration. This wrapper does not expose gradients
through integration. Its SBML scope matches the guarded autonomous JAX adapter.
Every state and absolute time is carried through exact external resets, and
only complete trajectories are returned. Comparison with a native SBML engine
is still required to check the shared JAX importer's interpretation.
"""

from functools import lru_cache
import hashlib
from pathlib import Path

import numpy as np

from .catalog_jax import observable_trajectory
from .jax_protocols import supported_model
from .native_protocols import encode_protocol, intervention_targets


@lru_cache(maxsize=4)
def _compiled_rhs(path, source_hash):
    import jax
    import jax.numpy as jnp
    from jaxkineticmodel.load_sbml.sbml_model import SBMLModel
    from jaxkineticmodel.load_sbml.jax_kinetic_model import (
        separate_params, construct_param_point_dictionary,
    )

    info = supported_model(path)
    if info["sha256"] != source_hash:
        raise ValueError("SBML source changed while preparing the reference")
    model = SBMLModel(path)
    ode = model.get_kinetic_model()
    if not jax.config.x64_enabled:
        raise ValueError("JAX 64-bit arithmetic is required")
    targets, _ = intervention_targets(path)
    if model.species_names != list(targets) or len(model.y0) != len(targets) or not targets:
        raise ValueError("JAX independent state inventory differs from SBML")
    global_params, local_params = separate_params(model.parameters)
    global_params = construct_param_point_dictionary(ode.v_symbols, ode.reaction_names, global_params)
    arguments = (global_params, local_params, jnp.zeros(len(ode.reaction_names)))
    raw = jax.jit(lambda t, y: ode.func(t, y, arguments))
    jacobian = jax.jit(jax.jacfwd(raw, argnums=1))
    rhs = lambda t, y: np.asarray(raw(t, jnp.asarray(y)))
    jac = lambda t, y: np.asarray(jacobian(t, jnp.asarray(y)))
    factors = np.array([model.compartments[model.model.getSpecies(s).getCompartment()]
                        if s in model.amount_species else 1. for s in model.species_names])
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != source_hash:
        raise ValueError("SBML source changed while preparing the reference")
    return model, ode, rhs, jac, factors, info["observables"]


def scipy_protocol_trajectory(path, times, trains, *, method="Radau", rtol=1e-10,
                              atol=1e-12, evidence=None, progress=None):
    """Run a full reset protocol with SciPy and a JAX-computed state Jacobian.

The optional progress callback receives evidence after each completed interval.
It can persist counters without retaining trajectory arrays. Source content,
not merely its path, identifies the cached derivative functions.
"""
    from scipy.integrate import solve_ivp

    path = Path(path).resolve()
    times = np.asarray(times, dtype=float)
    trains = tuple(trains)
    if (times.ndim != 1 or len(times) < 2 or not np.isfinite(times).all()
            or times[0] != 0 or np.any(np.diff(times) <= 0)):
        raise ValueError("Finite increasing sample times must start at zero")
    if not np.isfinite([rtol, atol]).all() or min(rtol, atol) <= 0:
        raise ValueError("Positive finite solver tolerances are required")
    if method not in ("Radau", "BDF"):
        raise ValueError("Choose Radau or BDF for the independent stiff reference")
    if any(t.stop > times[-1] for t in trains):
        raise ValueError("Reset train extends beyond the simulation window")
    supported_model(path)
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
    model, ode, rhs, jac, factors, observables = _compiled_rhs(str(path), source_hash)
    state = np.asarray(model.y0).copy()
    indices = {s: i for i, s in enumerate(model.species_names)}
    states = np.full((len(times), len(state)), np.nan)
    edges = np.r_[0., resets, times[-1]]
    evidence = {} if evidence is None else evidence
    evidence.update(model_sha256=source_hash, backend="scipy.solve_ivp", method=method,
        rhs_backend="Jaxkineticmodel", jacobian="jax.jacfwd", x64=True,
        rtol=rtol, atol=atol, initial_step="automatic", absolute_time_preserved=True,
        expected_resets=len(resets), performed_resets=0,
        expected_train_reset_counts=[len(t.indices()) if t.values else 0 for t in trains],
        train_reset_counts=[0]*len(trains), completed_segments=0, expected_segments=len(edges)-1,
        completed=False, sample_count=len(times), nfev=0, njev=0, nlu=0)
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
        solution = solve_ivp(rhs, (start, end), state, method=method, jac=jac,
                             t_eval=segment_times, rtol=rtol, atol=atol)
        for name in ("nfev", "njev", "nlu"):
            evidence[name] += int(getattr(solution, name))
        if not solution.success:
            raise RuntimeError(f"SciPy integration failed on [{start}, {end}]: {solution.message}")
        values = solution.y.T
        if values.shape != (len(segment_times), len(state)) or not np.isfinite(values).all():
            raise RuntimeError(f"Incomplete or non-finite SciPy segment on [{start}, {end}]")
        states[first:last] = values[np.searchsorted(segment_times, requested)]
        state = values[-1].copy()
        evidence["completed_segments"] += 1
        if progress is not None:
            progress(evidence)
    if (not np.isfinite(states).all() or evidence["performed_resets"] != len(resets)
            or evidence["train_reset_counts"] != evidence["expected_train_reset_counts"]):
        raise RuntimeError("SciPy protocol did not complete every sample and scheduled reset")
    result = observable_trajectory(model, ode, times, states, observables)
    evidence["completed"] = True
    return result
