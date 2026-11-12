"""A model-specific arbitrary-precision check of the five Marhl state equations.

The seven reaction fluxes below are transcribed independently from BioModel 39.
This accepts only the checksummed source model; it is not an SBML importer.
mpmath and Heyoka use separate implementations of the Taylor method, so their
agreement is not evidence of agreement between different integrator families.
"""

import hashlib
import math
from pathlib import Path

import numpy as np


MODEL_SHA256 = "6b221222be03747b11454cc4f2a6218697d9c6367d3578a170c7cc5c34ad3b12"
NAMES = ["Ca_cyt", "CaER", "CaM", "CaPr", "Pr"]


def equations(context):
    """Concentration derivatives, including the original 1/4 stoichiometries."""
    real = lambda value: context.mpf(float(value))
    kch,k1,kleak,kpump,kout,k3,km,kin,k2,kminus,kplus = map(real,
        (4100.,5.,.05,20.,125.,5.,.00625,300.,.8,.01,.1))
    quarter = real(.25)

    def rhs(t, state):
        c,e,m,b,p = state
        v1 = kch*c*c*(e-c)/(k1*k1+c*c)
        v3 = kleak*(e-c)
        v5 = kpump*c
        v7 = m*(kout*c*c/(k3*k3+c*c)+km)
        v9 = kin*c**8/(k2**8+c**8)
        v11 = kminus*b
        v12 = kplus*c*p
        return [v1+v3-v5+v7-v9+v11-v12, quarter*(v5-v1-v3),
                quarter*(v9-v7), v12-v11, v11-v12]

    return rhs, list(map(real, (.35,.76,.29,85.45,34.55)))


def trajectory(path, times, trains=(), *, precision=128, tolerance="1e-30", degree=32,
               evidence=None, progress=None):
    import mpmath

    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != MODEL_SHA256:
        raise ValueError("The independently transcribed equations require the original BioModel 39")
    if type(precision) is not int or precision < 64 or type(degree) is not int or degree < 4:
        raise ValueError("Require at least 64 precision bits and Taylor degree at least four")
    context = mpmath.mp.clone()
    context.prec = precision
    tol = context.mpf(tolerance)
    if not context.isfinite(tol) or tol <= 0:
        raise ValueError("Positive finite truncation tolerance required")
    times = np.asarray(times, dtype=float)
    if (times.ndim != 1 or len(times) < 2 or times[0] != 0
            or not np.isfinite(times).all() or np.any(np.diff(times) <= 0)):
        raise ValueError("Finite increasing observation times must start at zero")
    events, counts = {}, []
    for index, train in enumerate(trains):
        start, stop, interval = train["start"], train["stop"], train.get("interval", .1)
        if (not np.isfinite([start, stop, interval]).all() or start < 0 or stop <= start
                or stop > times[-1] or interval <= 0):
            raise ValueError("Invalid reset interval")
        n = round((stop-start)/interval)
        if n < 1 or not np.isclose(n*interval, stop-start, rtol=0, atol=1e-9):
            raise ValueError("Reset duration must be an integer multiple of interval")
        values = train["values"]
        if set(values)-set(NAMES) or any(not math.isfinite(v) or v < 0 for v in values.values()):
            raise ValueError("Only model species can receive finite nonnegative resets")
        selected = range(0 if train.get("include_start", False) else 1, n+int(train.get("include_stop", False)))
        counts.append(len(selected) if values else 0)
        if not values:
            continue
        for when in start+np.asarray(list(selected))*interval:
            event = events.setdefault(float(when), {"values": {}, "trains": []})
            if set(event["values"]) & values.keys():
                raise ValueError("Conflicting simultaneous resets")
            event["values"].update(values)
            event["trains"].append(index)
    resets = np.asarray(sorted(events))
    if len(resets):
        if resets[0] <= 0 or resets[-1] >= times[-1] or np.any(np.diff(resets) <= 1e-10):
            raise ValueError("Distinct resets strictly inside the observation window are required")
        positions = np.searchsorted(times, resets)
        if np.any(np.minimum(abs(times[positions]-resets), abs(times[positions-1]-resets)) <= 1e-10):
            raise ValueError("Samples must avoid ambiguous reset instants")
    evidence = {} if evidence is None else evidence
    evidence.update(model_sha256=MODEL_SHA256, backend="mpmath.odefun", mpmath_version=mpmath.__version__,
        precision_bits=precision, tolerance=str(tol), degree=degree,
        numeric_inputs="binary64 values promoted exactly", absolute_time_preserved=True,
        expected_resets=len(resets), performed_resets=0, expected_train_reset_counts=counts,
        train_reset_counts=[0]*len(trains), expected_segments=len(resets)+1, completed_segments=0,
        rhs_evaluations=0, sample_count=len(times), observables=NAMES, completed=False)
    raw_rhs, state = equations(context)
    def rhs(t, state):
        evidence["rhs_evaluations"] += 1
        return raw_rhs(t, state)
    real = lambda value: context.mpf(float(value))
    indices = {name: index for index,name in enumerate(NAMES)}
    values = np.full((len(times), len(NAMES)), np.nan)
    edges = np.r_[0., resets, times[-1]]
    for start,end in zip(edges[:-1], edges[1:]):
        if start in events:
            for name,value in events[start]["values"].items():
                state[indices[name]] = real(value)
            evidence["performed_resets"] += 1
            for index in events[start]["trains"]:
                evidence["train_reset_counts"][index] += 1
        solution = context.odefun(rhs, real(start), state, tol=tol, degree=degree)
        first = np.searchsorted(times, start)
        last = np.searchsorted(times, end, side="right" if end == times[-1] else "left")
        for index in range(first,last):
            values[index] = [float(x) for x in solution(real(times[index]))]
        state = list(solution(real(end)))
        evidence["last_interval"] = [float(start),float(end)]
        evidence["completed_segments"] += 1
        if progress is not None:
            progress(evidence)
    if (not np.isfinite(values).all() or evidence["performed_resets"] != len(resets)
            or evidence["train_reset_counts"] != counts):
        raise RuntimeError("The complete trajectory and every reset are required")
    evidence["completed"] = True
    return NAMES.copy(), values
