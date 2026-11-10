"""Delay-preserving validation of the catalog's Scheper1999 model.

This adapter is intentionally specific to the checked BioModels encoding. Its
two equations are extracted in concentration units (the common volume cancels).
The original SBML file remains unchanged. Constant prehistory follows its
constant initial amounts and fixed compartment, with no initial assignments.
"""

import hashlib
from pathlib import Path

import libsbml
import numpy as np
import pandas as pd

MODEL_SHA256 = "748514f402eea94c49346701a30f2b429c9c7d5de922cd450e5a155d5f69dbe1"


def parameters(path):
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != MODEL_SHA256:
        raise ValueError("Scheper adapter requires the validated original SBML encoding")
    model = libsbml.readSBML(str(path)).getModel()
    result = {p.getId(): p.getValue() for reaction in model.getListOfReactions()
              for p in reaction.getKineticLaw().getListOfParameters()}
    initial = []
    for sid in ("M", "P"):
        species = model.getSpecies(sid)
        volume = model.getCompartment(species.getCompartment()).getSize()
        initial.append(species.getInitialAmount()/volume)
    return result, np.array(initial)


def method_of_steps(rhs, times, initial, delay, *, rtol=1e-10, atol=1e-12):
    """One positive constant delay, constant prehistory, DOP853 dense output.

Each interval is at most one delay long, so the delayed argument comes entirely
from already solved history. No interpolation across an unsolved future occurs.
"""
    from scipy.integrate import solve_ivp
    times = np.asarray(times, dtype=float)
    initial = np.asarray(initial, dtype=float)
    if delay <= 0 or times[0] != 0 or np.any(np.diff(times) <= 0):
        raise ValueError("Positive delay and increasing samples starting at zero required")
    segments = []
    def past(at):
        if at <= 0:
            return initial
        index = min(int(at/delay), len(segments)-1)
        if index < 0:
            raise ValueError("Requested unsolved history")
        return segments[index].sol(at)
    current = initial
    for n in range(int(np.ceil(times[-1]/delay))):
        start, stop = n*delay, min((n+1)*delay, times[-1])
        segment = solve_ivp(lambda t, state: rhs(t, state, past(t-delay)),
                            (start, stop), current, method="DOP853", rtol=rtol,
                            atol=atol, dense_output=True, max_step=delay/4)
        if not segment.success:
            raise RuntimeError(segment.message)
        segments.append(segment)
        current = segment.y[:, -1]
    return np.array([initial if t == 0 else
                     segments[min(int(t/delay), len(segments)-1)].sol(t) for t in times])


def compiled_delay(expressions, times, initial, delay, *, step=.001):
    """Independent JiTCDDE integration with a checked fixed-step refinement.

An initial microscopic step resolves the initial derivative discontinuity while
preserving the prescribed constant history to numerical precision. We retain
the actual initial point rather than discarding an initial delay-sized window.
"""
    from jitcdde import jitcdde
    if step <= 0 or step >= delay:
        raise ValueError("Integration step must be positive and smaller than delay")
    solver = jitcdde(expressions, delays=[delay], verbose=False)
    solver.constant_past(initial)
    solver.compile_C()
    solver.integrate_blindly(min(1e-10, times[1]/100), step=1e-10)
    values = [np.array(initial)]
    for target in times[1:]:
        values.append(solver.integrate_blindly(float(target), step=step))
    return np.asarray(values)


def trajectory(path, times, engine, *, rtol=1e-10, atol=1e-12, step=.001):
    p, initial = parameters(path)
    delay = p["parameter_0000009"]
    if engine == "scipy-method-of-steps":
        def rhs(t, state, delayed):
            m, protein = state
            return np.array([p["rM"]/(1+(protein/p["k"])**p["n"])-p["qM"]*m,
                             p["rP"]*delayed[0]**p["m"]-p["qP"]*protein])
        values = method_of_steps(rhs, times, initial, delay, rtol=rtol, atol=atol)
    elif engine == "jitcdde":
        from jitcdde import t, y
        # Kept separate from the numerical RHS for independent code generation.
        expressions = [p["rM"]/(1+(y(1)/p["k"])**p["n"])-p["qM"]*y(0),
                       p["rP"]*y(0, t-delay)**p["m"]-p["qP"]*y(1)]
        values = compiled_delay(expressions, times, initial, delay, step=step)
    else:
        raise ValueError(f"Unknown delay engine {engine}")
    if not np.isfinite(values).all():
        raise ValueError("Non-finite delay trajectory")
    return pd.DataFrame({"time": times, "EmptySet": np.zeros(len(times)),
                         "M": values[:, 0], "P": values[:, 1]})
