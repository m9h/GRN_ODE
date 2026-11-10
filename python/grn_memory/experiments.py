"""Experiments corresponding to the questions in Biswas et al. (2023)."""

import numpy as np

from .analysis import regulation, retained, retention_fraction
from .simulation import Phase, model_info, simulate


def window(trace, phase, species):
    return trace.loc[trace.phase == phase, species].to_numpy()


def prepare(path, engine="roadrunner", duration=50, **kwargs):
    baseline = simulate(path, [Phase("baseline", duration)], engine=engine, **kwargs)
    dynamic = model_info(path)[1]
    state = baseline.iloc[-1][dynamic].to_dict()
    return baseline, state


def stimulus(baseline, species, direction):
    if direction not in (-1, 1):
        raise ValueError("Use +1 (up) or -1 (down)")
    return {species: float(baseline[species].max() * 100 if direction == 1
                           else baseline[species].min() / 100)}


def retention_experiment(path, us, response, direction, *, engine="roadrunner",
                         duration=50, **kwargs):
    b, state = prepare(path, engine, duration, **kwargs)
    clamp = stimulus(b, us, direction)
    phases = [Phase("train", duration, clamp), Phase("relax", duration),
              Phase("long_relax", 10 * duration)]
    run = lambda ps: simulate(path, ps, initial=state, start=duration, engine=engine, **kwargs)
    trained = run(phases)
    control = run([Phase(p.name, p.duration) for p in phases])
    on, off = window(trained, "train", response), window(trained, "relax", response)
    response_direction = regulation(b[response], on, window(control, "train", response))
    score = {
        "stimulus": us, "response": response, "clamp": clamp,
        "response_direction": response_direction,
        "baseline_mean": float(b[response].mean()), "training_mean": float(on.mean()),
        "relaxation_mean": float(off.mean()),
        "retained_fraction": retention_fraction(b[response], on, off),
        "ucs_memory": retained(b[response], on, off, response_direction) if response_direction else False,
        "late_mean": float(window(trained, "long_relax", response)[-1001:].mean()),
        "late_control_mean": float(window(control, "long_relax", response)[-1001:].mean()),
    }
    return {"baseline": b, "trained": trained, "control": control}, score


def association_experiment(path, us, us_direction, cs, cs_direction, response, *,
                           engine="roadrunner", duration=50, **kwargs):
    """Test neutral cue, UCS-only transfer, pairing, recall and delayed recall.

    Paper-like labels are reported separately from the extra sham-probe check.
    Consolidation uses an actual delayed CS rechallenge, as described in the paper.
    """
    if len({us, cs, response}) != 3:
        raise ValueError("UCS, CS and response must be distinct")
    b, state = prepare(path, engine, duration, **kwargs)
    u, c = stimulus(b, us, us_direction), stimulus(b, cs, cs_direction)
    def run(training, probe, delay=False):
        phases = [Phase("train", duration, training), Phase("wash", duration)]
        if delay:
            phases.append(Phase("delay", duration))
        phases += [Phase("probe", duration, probe), Phase("recall", duration)]
        return simulate(path, phases, initial=state, start=duration, engine=engine, **kwargs)
    traces = {"baseline": b, "control": run({}, {}), "naive_cs": run(c, {}),
              "ucs": run(u, c), "paired": run(u | c, c),
              "paired_sham": run(u | c, {}), "ucs_sham": run(u, {}),
              "delayed": run(u | c, c, True), "delayed_sham": run(u | c, {}, True)}
    w = lambda name, phase: window(traces[name], phase, response)
    ud = regulation(b[response], w("ucs", "train"), w("control", "train"))
    cd = regulation(b[response], w("naive_cs", "train"), w("control", "train"))
    pretest = ud != 0 and cd == 0
    pair_dir = regulation(b[response], w("paired", "train"), w("control", "train"))
    association_training_dir = regulation(b[response], w("paired", "train"), w("control", "train"), 1.5)
    def probe(name):
        return regulation(w(name, "wash"), w(name, "probe"), w("control", "probe"), 1.5)
    transfer_dir, assoc_dir = probe("ucs"), probe("paired")
    transfer = pretest and transfer_dir != 0
    association = pretest and association_training_dir != 0 and assoc_dir != 0 and not transfer
    sham_dir = regulation(w("paired_sham", "probe"), w("paired", "probe"),
                          w("paired_sham", "probe"), 1.5)
    # Delayed causal check uses a time-matched continuation from identical training.
    delayed_dir = regulation(w("delayed", "delay"), w("delayed", "probe"),
                             w("delayed_sham", "probe"), 1.5)
    score = {
        "us": u, "cs": c, "response": response, "pretest_passed": pretest,
        "ucs_direction": ud, "naive_cs_direction": cd,
        "ucs_memory": bool(ud and retained(b[response], w("ucs", "train"), w("ucs", "wash"), ud)),
        "pairing_memory": bool(pair_dir and retained(b[response], w("paired", "train"), w("paired", "wash"), pair_dir)),
        "transfer_memory": bool(transfer), "associative_memory": bool(association),
        "long_recall": bool(association and retained(w("paired", "wash"), w("paired", "probe"), w("paired", "recall"), assoc_dir)),
        "short_recall": bool(association and not retained(w("paired", "wash"), w("paired", "probe"), w("paired", "recall"), assoc_dir)),
        "consolidation_candidate": bool(pretest and association_training_dir and not transfer and not assoc_dir and delayed_dir),
        "paired_probe_direction": assoc_dir,
        "probe_differs_from_paired_sham": bool(sham_dir),
        "means": {name: {p: float(g[response].mean()) for p, g in t.groupby("phase", sort=False)}
                  for name, t in traces.items()},
    }
    return traces, score


def repeated_experiment(path, us, response, direction, *, engine="roadrunner",
                        duration=50, pulses=6, **kwargs):
    """Increasing on/off durations used in Find_DrugRes_Sensitize_SLURM1.m.

    In addition to absolute response, measure each pulse against its own preceding
    rest window and an untreated trajectory. Accumulation alone is not sensitization.
    """
    b, state = prepare(path, engine, duration, **kwargs)
    phases = []
    for k in range(pulses):
        phases += [Phase(f"pulse_{k+1}", duration + 10 * k),
                   Phase(f"rest_{k+1}", duration + 10 * (k+1))]
    run = lambda ps: simulate(path, ps, initial=state, start=duration, engine=engine, **kwargs)
    control = run(phases)
    # Unlike memory evaluation, the drug script calibrates against the entire
    # untreated run and excludes exact zeros when computing its minimum.
    natural = np.concatenate([b[us].to_numpy(), control[us].to_numpy()])
    nonzero = natural[natural > 0]
    level = float(natural.max()*100 if direction == 1 else (nonzero.min()/100 if nonzero.size else 0))
    clamp = {us: level}
    phases = [Phase(p.name, p.duration, clamp, True, True) if p.name.startswith("pulse") else p
              for p in phases]
    treated = run(phases)
    rows = []
    for k in range(1, pulses+1):
        pre = b[response].to_numpy() if k == 1 else window(treated, f"rest_{k-1}", response)
        on = window(treated, f"pulse_{k}", response)
        ref = window(control, f"pulse_{k}", response)
        rows.append({"pulse": k, "duration": duration + 10*(k-1), "pre_mean": float(pre.mean()),
                     "on_mean": float(on.mean()), "increment": float(on.mean()-pre.mean()),
                     "untreated_mean": float(ref.mean()),
                     "direction": regulation(pre, on, ref, 1.5)})
    return {"baseline": b, "treated": treated, "control": control}, {
        "stimulus": us, "response": response, "clamp": clamp, "pulses": rows,
        "absolute_response_rises": bool(rows[-1]["on_mean"] > rows[0]["on_mean"]),
        "absolute_response_falls": bool(rows[-1]["on_mean"] < rows[0]["on_mean"]),
    }


def breaking_experiment(path, us, response, direction, breaker, breaker_direction,
                        *, engine="roadrunner", **kwargs):
    """Rechallenge the same conditioned state with and without a second input."""
    traces, repeated_score = repeated_experiment(path, us, response, direction,
                                                 engine=engine, **kwargs)
    dynamic = model_info(path)[1]
    state = traces["treated"].iloc[-1][dynamic].to_dict()
    time = float(traces["treated"].time.iloc[-1])
    natural = np.concatenate([traces["baseline"][breaker], traces["control"][breaker]])
    nonzero = natural[natural > 0]
    level = float(natural.max()*100 if breaker_direction == 1 else
                  (nonzero.min()/100 if nonzero.size else 0))
    def run(clamp):
        phases = [Phase("break", 100, clamp), Phase("recover", 100),
                  Phase("rechallenge", 100, repeated_score["clamp"]), Phase("relax", 100)]
        return simulate(path, phases, initial=state, start=time, engine=engine, **kwargs)
    traces["breaking"] = run({breaker: level})
    traces["sham_breaking"] = run({})
    score = {"repeated": repeated_score, "breaker": {breaker: level},
             "response": response, "means": {}}
    for key in ("breaking", "sham_breaking"):
        pre, on = window(traces[key], "recover", response), window(traces[key], "rechallenge", response)
        score["means"][key] = {"pre": float(pre.mean()), "rechallenge": float(on.mean()),
                               "increment": float(on.mean()-pre.mean())}
    return traces, score
