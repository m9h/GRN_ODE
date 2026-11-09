"""External resets with retained delay history for the Scheper clock.

The method-of-steps solver represents instantaneous, right-continuous jumps.
JiTCDDE approximates them over a declared narrow width; comparisons must include
step/width refinement. Neither solver replaces the past with a new constant.
"""

from bisect import bisect_right

import numpy as np
import pandas as pd

from .scheper_delay import parameters


def resets_from_trains(trains, symbols):
    resets = {}
    for train in trains:
        for when in train.times():
            state = resets.setdefault(round(float(when), 10), {})
            for symbol, value in train.values.items():
                if symbol not in symbols or not np.isfinite(value) or value < 0:
                    raise ValueError("Invalid delay-model reset target or value")
                index = symbols.index(symbol)
                if index in state:
                    raise ValueError("Conflicting simultaneous resets")
                state[index] = float(value)
    return resets


def steps_with_resets(rhs, times, initial, delay, resets, *, rtol=1e-10, atol=1e-12):
    """Method of steps split at jumps and their delayed discontinuities."""
    from scipy.integrate import solve_ivp
    times = np.asarray(times, dtype=float)
    if delay <= 0 or times[0] != 0 or np.any(np.diff(times) <= 0):
        raise ValueError("Positive delay and increasing samples from zero required")
    initial = np.asarray(initial, dtype=float)
    end = float(times[-1])
    # Every propagated discontinuity is an integration boundary. Also include
    # multiples of the delay so no segment ever reads its own unsolved future.
    edges = {0., end}
    for origin in [0., *resets]:
        if origin < 0 or origin > end:
            raise ValueError("Reset outside simulation window")
        for n in range(int(np.floor((end-origin)/delay))+1):
            edges.add(min(end, round(origin+n*delay, 10)))
    edges = sorted(edges)
    segments, starts, right_states = [], [], {}
    current = initial.copy()

    def past(at):
        if at < 0:
            return initial
        if at in right_states:
            return right_states[at]
        index = bisect_right(starts, at)-1
        if index < 0:
            return initial
        if at > segments[index].t[-1]+1e-9:
            raise ValueError("Requested unsolved delay history")
        return segments[index].sol(at)

    for start, stop in zip(edges[:-1], edges[1:]):
        for index, value in resets.get(start, {}).items():
            current[index] = value
        right_states[start] = current.copy()
        # At the endpoint, use the left derivative. The next segment starts
        # with the right derivative after any delayed/direct discontinuity.
        def fun(t, state):
            at = min(t, np.nextafter(stop, start))
            return rhs(at, state, past(at-delay))
        segment = solve_ivp(fun, (start, stop), current, method="DOP853", rtol=rtol,
                            atol=atol, dense_output=True, max_step=min(delay/4, stop-start))
        if not segment.success:
            raise RuntimeError(segment.message)
        starts.append(start)
        segments.append(segment)
        current = segment.y[:, -1].copy()
    for index, value in resets.get(end, {}).items():
        current[index] = value
    right_states[end] = current
    return np.array([past(float(t)) for t in times])


def jitcdde_with_resets(expressions, times, initial, delay, resets, *, step=.001, jump_width=1e-9):
    """Fixed-step independent integration, with narrow explicit history jumps."""
    from jitcdde import jitcdde
    if not 0 < jump_width < step < delay:
        raise ValueError("Require 0 < jump_width < step < delay")
    solver = jitcdde(expressions, delays=[delay], verbose=False)
    solver.constant_past(initial)
    solver.compile_C()
    state = np.asarray(initial, dtype=float).copy()
    values = []
    event_times = sorted(resets)
    cursor = 0
    solver.integrate_blindly(1e-10, step=1e-10)
    for target in times:
        target = float(target)
        while cursor < len(event_times) and event_times[cursor] <= target:
            when = event_times[cursor]
            if when < solver.t:
                raise ValueError("Reset precedes current delay solver time")
            state = solver.integrate_blindly(when, step=step)
            amplitude = np.zeros(len(initial))
            for index, value in resets[when].items():
                amplitude[index] = value-state[index]
            # Backward-width jump ends at the scheduled instant. This keeps all
            # future integration targets at or beyond the current time.
            solver.jump(amplitude, when, width=jump_width, forward=False)
            state = state + amplitude
            cursor += 1
        if target == 0:
            values.append(np.asarray(initial).copy())
        elif target > solver.t:
            state = solver.integrate_blindly(target, step=step)
            values.append(state.copy())
        else:
            values.append(state.copy())
    return np.asarray(values)


def delay_protocol_trajectory(path, times, trains, engine, *, rtol=1e-10, atol=1e-12,
                              step=.001, jump_width=1e-9):
    p, initial = parameters(path)
    delay = p["parameter_0000009"]
    resets = resets_from_trains(trains, ["M", "P"])
    if engine == "scipy-method-of-steps":
        def rhs(t, state, delayed):
            m, protein = state
            return [p["rM"]/(1+(protein/p["k"])**p["n"])-p["qM"]*m,
                    p["rP"]*delayed[0]**p["m"]-p["qP"]*protein]
        values = steps_with_resets(rhs, times, initial, delay, resets, rtol=rtol, atol=atol)
    elif engine == "jitcdde":
        from jitcdde import t, y
        expressions = [p["rM"]/(1+(y(1)/p["k"])**p["n"])-p["qM"]*y(0),
                       p["rP"]*y(0, t-delay)**p["m"]-p["qP"]*y(1)]
        values = jitcdde_with_resets(expressions, times, initial, delay, resets,
                                     step=step, jump_width=jump_width)
    else:
        raise ValueError(f"Unknown delay engine {engine}")
    if not np.isfinite(values).all():
        raise ValueError("Non-finite delay trajectory")
    return pd.DataFrame({"time": times, "EmptySet": np.zeros(len(times)),
                         "M": values[:, 0], "P": values[:, 1]})
