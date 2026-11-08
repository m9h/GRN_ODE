"""Periodic interventions, matching stimulateRelaxSingle.m's reset convention.

Concentrations are reset after each 0.1-unit integration block except the last.
The first block is unforced; intermediate boundary samples are post-reset.
Only autonomous reaction models with fixed compartments/parameters are supported.
This intentionally does not claim general SBML restart/event semantics.
"""

from dataclasses import dataclass, field
from pathlib import Path

import libsbml
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Phase:
    name: str
    duration: float = 50.0
    clamp: dict[str, float] = field(default_factory=dict)
    clamp_at_start: bool = False
    clamp_at_end: bool = False


def model_info(path):
    doc = libsbml.readSBML(str(path))
    if doc.getNumErrors(libsbml.LIBSBML_SEV_ERROR):
        raise ValueError(doc.getErrorLog().toString())
    m = doc.getModel()
    if m is None or m.getNumEvents() or m.getNumInitialAssignments():
        raise ValueError("Expected an autonomous reaction model without events/initial assignments")
    if any(not c.getConstant() or c.getSize() <= 0 for c in m.getListOfCompartments()):
        raise ValueError("Only fixed, positive compartment volumes are supported")
    if any(not p.getConstant() for p in m.getListOfParameters()):
        raise ValueError("Only fixed global parameters are supported")
    if m.getNumRules():
        raise ValueError("Rule-based models require additional restart validation")
    def has_time(ast):
        return ast is not None and (ast.getType() == libsbml.AST_NAME_TIME or
                                    any(has_time(ast.getChild(i)) for i in range(ast.getNumChildren())))
    maths = [r.getKineticLaw().getMath() for r in m.getListOfReactions()]
    maths += [r.getMath() for r in m.getListOfRules()]
    maths += [f.getMath() for f in m.getListOfFunctionDefinitions()]
    if any(has_time(x) for x in maths):
        raise ValueError("Time-dependent models require full state/restart semantics")
    assigned = {r.getVariable() for r in m.getListOfRules()}
    ids = [s.getId() for s in m.getListOfSpecies()]
    dynamic = [s.getId() for s in m.getListOfSpecies()
               if not s.getBoundaryCondition() and not s.getConstant() and s.getId() not in assigned]
    return ids, dynamic


class RoadRunner:
    def __init__(self, path, ids, dynamic, rtol, atol):
        import roadrunner
        self.model = roadrunner.RoadRunner(str(path))
        self.model.conservedMoietyAnalysis = False
        self.model.integrator.relative_tolerance = rtol
        self.model.integrator.absolute_tolerance = atol
        self.ids = ids
        self.dynamic = dynamic

    def initial(self):
        return {s: float(self.model[f"[{s}]"]) for s in self.dynamic}

    def block(self, times, state):
        for s, v in state.items():
            self.model[f"[{s}]"] = v
        self.model.time = float(times[0])
        a = np.asarray(self.model.simulate(times=list(times),
                       selections=["time"] + [f"[{s}]" for s in self.ids]))
        return a[:, 1:]

    def close(self):
        pass


class Copasi:
    def __init__(self, path, ids, dynamic, rtol, atol):
        import basico
        self.model = basico.load_model(str(path))
        if self.model is None:
            raise ValueError(f"COPASI could not load {path}")
        self.ids, self.dynamic, self.rtol, self.atol = ids, dynamic, rtol, atol
        self.species = {s.getSBMLId(): s for s in self.model.getModel().getMetabolites()}

    def initial(self):
        return {s: float(self.species[s].getInitialConcentration()) for s in self.dynamic}

    def block(self, times, state):
        import basico
        m = self.model.getModel()
        # Reinitialize every independent concentration together, including
        # changed conserved totals.
        for s, v in state.items():
            species = self.species[s]
            species.setInitialConcentration(float(v))
            m.updateInitialValues(species.getInitialConcentrationReference())
        # Restart autonomous blocks at zero and relabel with protocol time,
        # avoiding reliance on initial-time/task-output offset conventions.
        local_times = times - times[0]
        m.setInitialTime(0.0)
        out = basico.run_time_course(
            model=self.model, values=list(local_times), method="deterministic",
            use_initial_values=True, automatic=False, use_sbml_id=True,
            use_concentrations=True, r_tol=self.rtol, a_tol=self.atol,
        )
        np.testing.assert_allclose(out.index, local_times, atol=1e-8, rtol=0)
        # COPASI omits fixed boundary species from its default time series.
        for s in self.ids:
            if s not in out.columns:
                if s in self.dynamic:
                    raise ValueError(f"COPASI omitted dynamic species {s}")
                out[s] = float(self.species[s].getConcentration())
        return out.loc[:, self.ids].to_numpy()

    def close(self):
        import COPASI
        COPASI.CRootContainer.removeDatamodel(self.model)


def _steps(duration, dt):
    n = round(duration / dt)
    if duration <= 0 or dt <= 0 or n < 1 or not np.isclose(n * dt, duration):
        raise ValueError("Duration must be a positive integer multiple of the sampling interval")
    return n


def simulate(path: str | Path, phases: list[Phase], *, engine="roadrunner",
             initial=None, start=0.0, dt=0.01, reset_interval=0.1,
             rtol=1e-9, atol=1e-11):
    """Return concentration samples with separate (duplicated) phase boundaries.

Each phase has its own inclusive window, as in the MATLAB routines. Clamps are
external additions/removals of material, not changes to reaction parameters.
"""
    ids, dynamic = model_info(path)
    stride = _steps(reset_interval, dt)
    for phase in phases:
        n = _steps(phase.duration, dt)
        if phase.clamp and n % stride:
            raise ValueError("Stimulated phase duration must be a multiple of reset_interval")
        if set(phase.clamp) - set(dynamic):
            raise ValueError("Only independent, dynamic species can be clamped")
        if any(not np.isfinite(v) or v < 0 for v in phase.clamp.values()):
            raise ValueError("Clamp concentrations must be finite and nonnegative")
    if engine not in {"roadrunner", "copasi", "jaxkineticmodel"}:
        raise ValueError(f"Unknown engine: {engine}")
    if engine == "jaxkineticmodel":
        from .jaxkinetic import JaxKinetic
        solver_type = JaxKinetic
    else:
        solver_type = RoadRunner if engine == "roadrunner" else Copasi
    solver = solver_type(path, ids, dynamic, rtol, atol)
    try:
        state = solver.initial()
        if initial is not None:
            if set(initial) != set(dynamic) or not np.isfinite(list(initial.values())).all():
                raise ValueError("Initial state must specify every independent species")
            state = dict(initial)
        frames = []
        for phase in phases:
            n = _steps(phase.duration, dt)
            times = start + np.arange(n + 1) * dt
            values = np.empty((n + 1, len(ids)))
            blocksize = stride if phase.clamp else n
            if phase.clamp_at_start:
                state.update(phase.clamp)
            for i in range(0, n, blocksize):
                stop = min(i + blocksize, n)
                chunk = solver.block(times[i:stop + 1], state)
                values[i:stop + 1] = chunk
                state = {s: float(chunk[-1, ids.index(s)]) for s in dynamic}
                if stop < n:
                    state.update(phase.clamp)
            if phase.clamp_at_end:
                state.update(phase.clamp)
            if not np.isfinite(values).all():
                raise RuntimeError(f"Non-finite trajectory in {phase.name}")
            frame = pd.DataFrame(values, columns=ids)
            frame.insert(0, "time", times)
            frame.insert(1, "phase", phase.name)
            frames.append(frame)
            start = float(times[-1])
        return pd.concat(frames, ignore_index=True)
    finally:
        solver.close()
