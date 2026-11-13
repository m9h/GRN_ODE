"""Arbitrary-precision reference for a restricted autonomous SBML subset.

All state coordinates are concentrations. Numeric inputs returned by libSBML
and the recorded reset plan are promoted from binary64 exactly, so increasing
arithmetic precision does not silently change the supplied model coefficients.
Native events, rules, functions, initial assignments and dynamic compartments
are rejected. This is an optional diagnostic, not a general SBML simulator.
"""

from functools import reduce
from contextlib import nullcontext
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import libsbml
import numpy as np


def _model(path, precision):
    import heyoka as hy
    document = libsbml.readSBMLFromFile(str(path))
    model = document.getModel()
    if model is None or document.getNumErrors(libsbml.LIBSBML_SEV_ERROR):
        raise ValueError("Invalid SBML model")
    if (model.getNumEvents() or model.getNumRules() or model.getNumInitialAssignments()
            or model.getNumFunctionDefinitions() or model.isSetConversionFactor()):
        raise ValueError("Taylor reference does not support events, rules, initial assignments, functions or conversion factors")
    real = lambda value: hy.real(float(value), precision)
    constant = lambda value: hy.expression(real(value))
    compartments = {}
    for c in model.getListOfCompartments():
        if not c.getConstant() or c.getSpatialDimensions() == 0 or not math.isfinite(c.getSize()) or c.getSize() <= 0:
            raise ValueError("Fixed positive-volume compartments are required")
        compartments[c.getId()] = c.getSize()
    species = list(model.getListOfSpecies())
    names = [s.getId() for s in species]
    if not names:
        raise ValueError("At least one species is required")
    variables = [hy.make_vars(name) for name in names]
    scope = {name: constant(value) for name, value in compartments.items()}
    for p in model.getListOfParameters():
        if not p.getConstant() or not math.isfinite(p.getValue()):
            raise ValueError("Fixed finite global parameters are required")
        scope[p.getId()] = constant(p.getValue())
    initial, writable = [], set()
    for s, variable in zip(species, variables):
        if s.isSetConversionFactor():
            raise ValueError("Species conversion factors are unsupported")
        volume = compartments[s.getCompartment()]
        value = (real(s.getInitialConcentration()) if s.isSetInitialConcentration()
                 else real(s.getInitialAmount())/real(volume) if s.isSetInitialAmount() else real(0))
        if not np.isfinite(value):
            raise ValueError("Finite initial species values are required")
        initial.append(value)
        scope[s.getId()] = variable*constant(volume) if s.getHasOnlySubstanceUnits() else variable
        if not s.getConstant() and not s.getBoundaryCondition():
            writable.add(s.getId())

    def expression(node, environment):
        kind = node.getType()
        if node.isNumber():
            return constant(node.getValue())
        if kind == libsbml.AST_NAME:
            if node.getName() not in environment:
                raise ValueError("Unknown kinetic symbol: "+node.getName())
            return environment[node.getName()]
        children = [expression(node.getChild(i), environment) for i in range(node.getNumChildren())]
        if kind == libsbml.AST_PLUS:
            return reduce(lambda a, b: a+b, children, constant(0))
        if kind == libsbml.AST_TIMES:
            return reduce(lambda a, b: a*b, children, constant(1))
        if kind == libsbml.AST_MINUS:
            return -children[0] if len(children) == 1 else children[0]-children[1]
        if kind == libsbml.AST_DIVIDE:
            return children[0]/children[1]
        if kind in (libsbml.AST_POWER, libsbml.AST_FUNCTION_POWER):
            return children[0]**children[1]
        raise ValueError("Unsupported kinetic expression: "+libsbml.formulaToL3String(node))

    rates = {name: constant(0) for name in names}
    for reaction in model.getListOfReactions():
        if reaction.getFast() or reaction.getKineticLaw() is None:
            raise ValueError("Every non-fast reaction needs an explicit kinetic law")
        law = reaction.getKineticLaw()
        local = dict(scope)
        for p in (*law.getListOfParameters(), *law.getListOfLocalParameters()):
            if not math.isfinite(p.getValue()):
                raise ValueError("Finite local parameters are required")
            local[p.getId()] = constant(p.getValue())
        rate = expression(law.getMath(), local)
        for sign, references in ((-1, reaction.getListOfReactants()), (1, reaction.getListOfProducts())):
            for reference in references:
                if reference.isSetStoichiometryMath() or not math.isfinite(reference.getStoichiometry()):
                    raise ValueError("Fixed finite stoichiometry is required")
                name = reference.getSpecies()
                if name in writable:
                    volume = compartments[model.getSpecies(name).getCompartment()]
                    rates[name] += constant(sign)*constant(reference.getStoichiometry())*rate/constant(volume)
    return list(zip(variables, (rates[name] for name in names))), initial, names, writable


def taylor_trajectory(path, times, trains=(), *, precision=128, tolerance="1e-30", evidence=None, progress=None,
                      checkpoint=None, resume=False, checkpoint_every=10, stop_after_segments=None, max_seconds=None):
    """Integrate a full protocol, optionally saving exact state between segments.

Checkpoint stops are cooperative and occur after a complete segment. A single
long interval can exceed the requested wall budget. ``stop_after_segments``
counts segments computed by this invocation, including after a resume.
    """
    if type(checkpoint_every) is not int or checkpoint_every < 1:
        raise ValueError("Checkpoint interval must be a positive integer")
    if stop_after_segments is not None and (type(stop_after_segments) is not int or stop_after_segments < 1):
        raise ValueError("Segment budget must be a positive integer")
    if max_seconds is not None and (not math.isfinite(max_seconds) or max_seconds <= 0):
        raise ValueError("Wall budget must be finite and positive")
    if checkpoint is None and (stop_after_segments is not None or max_seconds is not None):
        raise ValueError("A cooperative stop requires a checkpoint")
    if checkpoint is None:
        if resume:
            raise ValueError("Resume requires a checkpoint path")
        lock = nullcontext()
    else:
        from .taylor_checkpoints import checkpoint_lock
        lock = checkpoint_lock(checkpoint, resume)
    with lock:
        return _taylor_trajectory(path, times, trains, precision=precision, tolerance=tolerance,
            evidence=evidence, progress=progress, checkpoint=checkpoint, resume=resume,
            checkpoint_every=checkpoint_every, stop_after_segments=stop_after_segments, max_seconds=max_seconds)


def _taylor_trajectory(path, times, trains, *, precision, tolerance, evidence, progress,
                       checkpoint, resume, checkpoint_every, stop_after_segments, max_seconds):
    """Integrate all requested samples, preserving state at external resets.

``trains`` contains dictionaries with the same explicit timing fields as
``native_protocols.ResetTrain``. Returned columns follow SBML species order.
Only the saved observations are rounded to binary64; internal state and dense
output use the requested precision throughout.
    """
    import heyoka as hy
    if checkpoint is not None:
        from . import taylor_checkpoints as checkpoints
    began = time.monotonic()
    if type(precision) is not int or precision < 64:
        raise ValueError("At least 64 bits of arithmetic precision are required")
    real = lambda value: hy.real(value, precision)
    tol = real(tolerance)
    if not np.isfinite(tol) or tol <= 0:
        raise ValueError("Positive finite Taylor tolerance required")
    times = np.asarray(times, dtype=float)
    if times.ndim != 1 or len(times) < 2 or times[0] != 0 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError("Finite increasing observation times must start at zero")
    equations, initial, names, writable = _model(path, precision)
    indices = {name: i for i, name in enumerate(names)}
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
        if set(values)-writable or any(not math.isfinite(v) or v < 0 for v in values.values()):
            raise ValueError("Only independent species can receive finite nonnegative resets")
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
    states = np.full((len(times), len(names)), np.nan)
    evidence = {} if evidence is None else evidence
    edges = np.r_[0., resets, times[-1]]
    evidence.update(model_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(), precision_bits=precision,
        tolerance=str(tol), high_accuracy=True, numeric_inputs="binary64 values promoted exactly",
        absolute_time_preserved=True, expected_resets=len(resets), performed_resets=0,
        expected_train_reset_counts=counts, train_reset_counts=[0]*len(trains),
        expected_segments=len(edges)-1, completed_segments=0, integration_steps=0,
        sample_count=len(times), observables=names, completed=False)
    identity = None
    if checkpoint is not None:
        identity = {"model_sha256": evidence["model_sha256"], "precision_bits": precision, "tolerance": str(tol),
            "observables": names, "times_sha256": hashlib.sha256(times.tobytes()).hexdigest(), "samples": len(times),
            "trains": json.loads(json.dumps(trains)), "high_accuracy": True, "compact_mode": True,
            "numeric_inputs": evidence["numeric_inputs"],
            "sources": {name: hashlib.sha256(Path(file).read_bytes()).hexdigest() for name, file in
                        (("adapter", __file__), ("checkpoints", checkpoints.__file__))},
            "environment": {"heyoka": hy.__version__, "numpy": np.__version__,
                            "libsbml": libsbml.getLibSBMLDottedVersion(), "python": platform.python_version(),
                            "system": platform.system(), "machine": platform.machine()}}
    resumed_segments = 0
    if resume:
        initial, observed, saved = checkpoints.load(checkpoint, identity, times, edges, events, dict(evidence), real)
        states[:len(observed)] = observed
        evidence.update(saved)
        resumed_segments = evidence["completed_segments"]
        evidence["resumed_from_checkpoint_segments"] = resumed_segments
        if evidence["completed"]:
            return names, states
    integrator = hy.taylor_adaptive(equations, initial, fp_type=hy.real, prec=precision,
                                    tol=tol, high_accuracy=True, compact_mode=True)
    integrator.time = real(float(edges[resumed_segments]))
    for start, end in zip(edges[resumed_segments:-1], edges[resumed_segments+1:]):
        if start in events:
            for name, value in events[start]["values"].items():
                integrator.state[indices[name]] = real(value)
            evidence["performed_resets"] += 1
            for index in events[start]["trains"]:
                evidence["train_reset_counts"][index] += 1
        first = np.searchsorted(times, start)
        last = np.searchsorted(times, end, side="right" if end == times[-1] else "left")
        requested = times[first:last]
        grid = np.unique(np.r_[start, requested, end])
        # propagate_grid can internally step past its final observation. The
        # final dense-output state is the exact segment endpoint for the reset.
        output = integrator.propagate_grid(np.asarray([real(float(t)) for t in grid], dtype=hy.real))
        if output[0] != hy.taylor_outcome.time_limit or output[5].shape != (len(grid), len(names)):
            raise RuntimeError("Taylor integration did not complete its observation grid")
        values = np.asarray(output[5], dtype=float)
        if not np.isfinite(values).all():
            raise RuntimeError("Nonfinite Taylor observation")
        states[first:last] = values[np.searchsorted(grid, requested)]
        integrator.state[:] = output[5][-1]
        integrator.time = real(float(end))
        evidence["integration_steps"] += int(output[3])
        evidence["completed_segments"] += 1
        evidence["last_interval"] = [float(start), float(end)]
        stopping = ((stop_after_segments is not None and evidence["completed_segments"] - resumed_segments >= stop_after_segments)
                    or (max_seconds is not None and time.monotonic() - began >= max_seconds))
        if checkpoint is not None and end != times[-1] and (stopping or evidence["completed_segments"] % checkpoint_every == 0):
            checkpoints.save(checkpoint, identity, integrator.state, states[:last], evidence, real)
        if progress is not None:
            progress(evidence)
        if stopping and end != times[-1]:
            raise checkpoints.TaylorCheckpointStop(f"Saved Taylor checkpoint after segment {evidence['completed_segments']}")
    if (not np.isfinite(states).all() or evidence["performed_resets"] != len(resets)
            or evidence["train_reset_counts"] != counts):
        raise RuntimeError("Taylor protocol did not complete every sample and reset")
    evidence["completed"] = True
    if checkpoint is not None:
        checkpoints.save(checkpoint, identity, integrator.state, states, evidence, real)
    return names, states
