"""State-preserving interventions on native SBML models.

One continuous simulation retains the model's clock, rule variables, and native
event state. External resets are encoded as events in a temporary SBML document;
the original model file is never modified. Values for species are concentrations
even when an SBML species symbol denotes an amount. Rate-rule parameters may also
be stimulated, in their native units. Derived quantities cannot be independent
inputs. Delay models require the separate history-preserving adapter.
"""

from dataclasses import dataclass
from pathlib import Path
import tempfile

import libsbml
import numpy as np

from .catalog_validation import inspect_model, native_trajectory


@dataclass(frozen=True)
class ResetTrain:
    """Resets from start through stop with explicit endpoint inclusion."""
    start: float
    stop: float
    values: dict[str, float]
    interval: float = .1
    include_start: bool = False
    include_stop: bool = False

    def indices(self):
        if not np.isfinite([self.start, self.stop, self.interval]).all():
            raise ValueError("Reset times must be finite")
        if self.start < 0 or self.stop <= self.start or self.interval <= 0:
            raise ValueError("Invalid reset interval")
        n = round((self.stop-self.start)/self.interval)
        if n < 1 or not np.isclose(n*self.interval, self.stop-self.start, rtol=0, atol=1e-9):
            raise ValueError("Reset duration must be an integer multiple of interval")
        return range(0 if self.include_start else 1, n+int(self.include_stop))

    def times(self):
        return self.start + np.array(list(self.indices())) * self.interval


def intervention_targets(path):
    """Return independently writable dynamical symbols and exclusions.

Boundary and constant species are retained as observables, not stimulated.
Rate-rule species/parameters are eligible because they are independent states.
"""
    doc = libsbml.readSBML(str(path))
    model = doc.getModel()
    if model is None or doc.getNumErrors(libsbml.LIBSBML_SEV_ERROR):
        raise ValueError(doc.getErrorLog().toString())
    if any(r.isAlgebraic() for r in model.getListOfRules()):
        raise ValueError("Algebraic constraints need an explicit intervention policy")
    assignment = {r.getVariable() for r in model.getListOfRules() if r.isAssignment()}
    rates = {r.getVariable() for r in model.getListOfRules() if r.isRate()}
    eligible, excluded = {}, {}
    for s in model.getListOfSpecies():
        sid = s.getId()
        reason = ("assignment rule" if sid in assignment else "constant" if s.getConstant()
                  else "boundary species" if s.getBoundaryCondition() and sid not in rates else None)
        if reason:
            excluded[sid] = reason
        else:
            eligible[sid] = "concentration"
    for p in model.getListOfParameters():
        if p.getId() in rates:
            eligible[p.getId()] = "rate-rule parameter"
    return eligible, excluded


def encode_protocol(path, trains):
    """Add one self-rearming clock event per reset train, without restarting time.

Integer counters compute event times from the original start and avoid repeated
floating-point addition. Train events must not write the same symbol at the same
time. Native events writing an intervention target are rejected until their
ordering is specified explicitly.
"""
    info = inspect_model(path)
    if info["delay_expressions"]:
        raise ValueError("Delay models need history-preserving interventions")
    allowed, _ = intervention_targets(path)
    doc = libsbml.readSBML(str(path))
    # L3 defines initial trigger values explicitly, including resets at time zero.
    if not doc.setLevelAndVersion(3, 2):
        raise ValueError("Could not convert protocol copy to SBML Level 3 Version 2")
    model = doc.getModel()
    event_targets = {a.getVariable() for e in model.getListOfEvents()
                     for a in e.getListOfEventAssignments()}
    occupied = set()
    for index, train in enumerate(trains):
        indices = train.indices()
        if not train.values or not len(indices):
            continue
        if set(train.values) - allowed.keys():
            raise ValueError("Only independent dynamical symbols may be reset")
        if set(train.values) & event_targets:
            raise ValueError("Native event and intervention write the same symbol")
        if any(not np.isfinite(v) or v < 0 for v in train.values.values()):
            raise ValueError("Reset values must be finite and nonnegative")
        for when in train.times():
            for symbol in train.values:
                key = (round(float(when), 10), symbol)
                if key in occupied:
                    raise ValueError("Conflicting simultaneous resets")
                occupied.add(key)
        prefix = f"grn_protocol_{index}"
        if any(model.getElementBySId(prefix+suffix) for suffix in ("_count", "_reset")):
            raise ValueError("Protocol symbol collides with an existing model symbol")
        counter = prefix + "_count"
        p = model.createParameter()
        p.setId(counter)
        p.setConstant(False)
        p.setValue(indices.start)
        p.setUnits("dimensionless")
        event = model.createEvent()
        event.setId(prefix + "_reset")
        event.setUseValuesFromTriggerTime(True)
        trigger = event.createTrigger()
        trigger.setInitialValue(False)
        trigger.setPersistent(True)
        trigger.setMath(libsbml.parseL3Formula(
            f"and({counter} < {indices.stop}, time >= {train.start:.17g} + {train.interval:.17g} * {counter})"))
        for symbol, value in {**train.values, counter: None}.items():
            assignment = event.createEventAssignment()
            assignment.setVariable(symbol)
            if symbol == counter:
                expression = f"{counter} + 1"
            else:
                expression = f"{value:.17g}"
                species = model.getSpecies(symbol)
                if species is not None and species.getHasOnlySubstanceUnits():
                    expression += " * " + species.getCompartment()
            assignment.setMath(libsbml.parseL3Formula(expression))
    encoded = libsbml.writeSBMLToString(doc)
    checked = libsbml.readSBMLFromString(encoded)
    if checked.getNumErrors(libsbml.LIBSBML_SEV_ERROR):
        raise ValueError(checked.getErrorLog().toString())
    return encoded


def protocol_trajectory(path, times, trains, engine, *, rtol=1e-10, atol=1e-12):
    """Run a complete protocol from the original initial state and time zero."""
    times = np.asarray(times, dtype=float)
    if times.ndim != 1 or len(times) < 2 or times[0] != 0 or np.any(np.diff(times) <= 0):
        raise ValueError("Increasing sample times must start at zero")
    if any(train.stop > times[-1] for train in trains):
        raise ValueError("Reset train extends beyond the simulation window")
    original_columns = ["time"] + inspect_model(path)["observables"]
    with tempfile.TemporaryDirectory(prefix="grn-protocol-") as directory:
        modified = Path(directory) / "protocol.xml"
        # Native solver libraries may change the process locale to ASCII.
        # SBML annotations/model names remain UTF-8 regardless of that locale.
        modified.write_text(encode_protocol(path, trains), encoding="utf-8")
        result = native_trajectory(modified, times, engine, rtol=rtol, atol=atol)
        for index, train in enumerate(trains):
            if train.values and len(train.indices()):
                actual = result[f"grn_protocol_{index}_count"].iloc[-1]
                if actual != train.indices().stop:
                    raise RuntimeError(f"Reset train {index} did not execute every scheduled reset")
    return result.loc[:, original_columns]


def sample_times(duration, dt, trains=(), *, post_reset_offset=1e-6):
    """Uniform grid, with coincident reset samples moved just after the reset.

Exact discontinuity samples can select either side because decimal times are
not exactly representable. The offset is recorded physical time, never relabeled
as the jump time. Both simulators and the untreated control use this same grid.
"""
    if not np.isfinite([duration, dt, post_reset_offset]).all() or min(duration, dt, post_reset_offset) <= 0:
        raise ValueError("Positive finite duration, sampling interval and offset required")
    n = round(duration/dt)
    if n < 1 or not np.isclose(n*dt, duration, rtol=0, atol=1e-9) or post_reset_offset >= dt/100:
        raise ValueError("Duration must be a multiple of dt and reset offset much smaller than dt")
    times = np.arange(n+1)*dt
    for train in trains:
        for event_time in train.times():
            i = round(event_time/dt)
            if 0 < i < len(times) and abs(times[i]-event_time) < 1e-9:
                if i == n:
                    raise ValueError("Final sample must be after the last reset")
                times[i] = event_time+post_reset_offset
    return times


