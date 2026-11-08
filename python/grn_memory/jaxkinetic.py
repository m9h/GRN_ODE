"""Optional Jaxkineticmodel adapter for the same autonomous reset experiments."""

from functools import lru_cache
from pathlib import Path

import numpy as np


@lru_cache(maxsize=8)
def _compiled(path, rtol, atol):
    import jax
    import jax.numpy as jnp
    from jaxkineticmodel.load_sbml.sbml_model import SBMLModel

    model = SBMLModel(path)
    ode = model.get_kinetic_model()
    ode._change_solver(ode.solver, rtol=rtol, atol=atol)
    ode.dt0 = 1e-4
    solve = jax.jit(lambda times, y0: ode(times, y0, model.parameters))
    factors = np.array([1/model.model.getCompartment(model.model.getSpecies(s).getCompartment()).getSize()
                        if s in model.amount_species else 1. for s in model.species_names])
    return model, solve, factors, jnp.asarray


class JaxKinetic:
    def __init__(self, path, ids, dynamic, rtol, atol):
        self.model, self.solve, self.factors, self.asarray = _compiled(str(Path(path).resolve()), rtol, atol)
        if self.model.species_names != dynamic:
            raise ValueError('Jaxkineticmodel state order differs from independent SBML species order')
        self.ids, self.dynamic = ids, dynamic
        self.fixed = {}
        for sid in set(ids)-set(dynamic):
            s = self.model.model.getSpecies(sid)
            volume = self.model.model.getCompartment(s.getCompartment()).getSize()
            self.fixed[sid] = s.getInitialConcentration() if s.isSetInitialConcentration() else s.getInitialAmount()/volume

    def initial(self):
        return dict(zip(self.dynamic, (np.asarray(self.model.y0)*self.factors).tolist()))

    def block(self, times, state):
        # All models reaching this adapter have passed model_info's autonomous,
        # fixed-compartment checks. Restarting local time therefore preserves RHS.
        initial = self.asarray([state[s] for s in self.dynamic])/self.factors
        values = np.asarray(self.solve(self.asarray(times-times[0]), initial))*self.factors
        return np.column_stack([values[:, self.dynamic.index(s)] if s in self.dynamic else
                                np.full(len(times), self.fixed[s]) for s in self.ids])

    def close(self):
        pass
