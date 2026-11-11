"""Locate native-solver failures under the original Goldbeter interventions.

M and X are active fractions in Goldbeter (1991). The catalog's 100x forcing
can take them outside [0, 1]. This diagnostic preserves that protocol and
records solver stopping states; it does not clip states or promote a failure.
"""

import argparse
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
import logging
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import basico
import COPASI
import numpy as np
import roadrunner

from grn_memory.catalog_breaking import branch_trains
from grn_memory.catalog_repeated import pulse_schedule, trains_for
from grn_memory.catalog_validation import PACKAGES, inspect_model
from grn_memory.native_protocols import ResetTrain, encode_protocol, sample_times


def state_summary(t, values):
    c, m, x = (float(values[k]) for k in ("C", "M", "X"))
    return {"time": float(t), "state": {"C": c, "M": m, "X": x},
        "activation_denominators": {"M": 1.005-m, "X": 1.005-x},
        "deactivation_denominators": {"M": .005+m, "X": .005+x},
        "cyclin_denominators": {"V1": .5+c, "degradation": .02+c},
        "fractions_outside_unit_interval": [k for k, v in (("M", m), ("X", x)) if not 0 <= v <= 1]}


def native_run(encoded, columns, grid, trains, engine, rtol, atol):
    if engine == "roadrunner":
        model = roadrunner.RoadRunner(encoded)
        model.conservedMoietyAnalysis = False
        model.integrator.relative_tolerance = rtol
        model.integrator.absolute_tolerance = atol
        model.integrator.maximum_num_steps = 100000
        result = {}
        try:
            values = np.asarray(model.simulate(times=list(grid), selections=["time"]+columns))
            result.update({"completed": len(values) == len(grid), "output_rows": len(values)})
        except RuntimeError as exc:
            result.update({"completed": False, "error": str(exc)})
        state = dict(zip(model.model.getFloatingSpeciesIds(), model.model.getFloatingSpeciesConcentrations()))
        result["terminal"] = state_summary(model.model.getTime(), state)
        result["terminal_state_caveat"] = (
            "Exposed model state after return; on failure RoadRunner need not copy "
            "the final internal CVODE state back to the model. The exposed time "
            "and state must not be treated as a synchronized accepted solution point.")
        result["terminal_rates"] = dict(zip(model.model.getFloatingSpeciesIds(),
                                            map(float, model.getRatesOfChange())))
        return result
    COPASI.CCopasiMessage.clearDeque()
    data = basico.load_model_from_string(encoded)
    try:
        model = data.getModel()
        refs = {s.getSBMLId(): s.getConcentrationReference() for s in model.getMetabolites()}
        refs.update({p.getSBMLId(): p.getValueReference() for p in model.getModelValues()})
        counters = [f"grn_protocol_{i}_count" for i, t in enumerate(trains)]
        selections = ["Time"]+[refs[k].getCN().getString() for k in columns+counters]
        frame = basico.run_time_course_with_output(selections, model=data, values=list(grid),
            use_initial_values=True, method="deterministic", automatic=False, output_event=False,
            r_tol=rtol, a_tol=atol, max_steps=100000)
        state = {s.getSBMLId(): s.getConcentration() for s in model.getMetabolites()}
        result = {"completed": frame.shape == (len(grid), len(selections)), "output_rows": len(frame),
                  "terminal": state_summary(model.getTime(), state)}
        if len(frame):
            last = dict(zip(["time"]+columns+counters, map(float, frame.iloc[-1])))
            result["last_output"] = state_summary(last["time"], last)
            result["reset_counters"] = {k: last[k] for k in counters}
            result["expected_final_counters"] = {k: t.indices().stop for k, t in zip(counters, trains)}
            if result["completed"]:
                result["completed"] = result["reset_counters"] == result["expected_final_counters"]
        result["native_messages"] = COPASI.CCopasiMessage.getAllMessageText()[-5000:]
        return result
    finally:
        COPASI.CRootContainer.removeDatamodel(data)


def diagnose(output):
    output.mkdir(parents=True, exist_ok=True)
    path = ROOT/"models/BIOMD0000000003.xml"
    reference_path = ROOT/"results/catalog-repeated/BIOMD0000000003.json"
    reference = json.loads(reference_path.read_text())
    info = inspect_model(path)
    assert info["sha256"] == reference["model_sha256"]
    possible = trains_for(pulse_schedule(), {})
    possible += [ResetTrain(t, t+100., {}) for t in (1010., 1210.)]
    grid = sample_times(1410., .01, possible, post_reset_offset=1e-5)
    probes = [("X__up", "M__up", True, False), ("X__up", "M__up", True, True),
              ("M__up", "X__up", False, True), ("M__up", "X__up", True, True)]
    report = {"purpose": __doc__, "model_sha256": info["sha256"],
        "reference_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_paper": "https://doi.org/10.1073/pnas.88.20.9107",
        "source_location": "Goldbeter 1991, page 9108, equations 1-2 and following paragraph",
        "biological_domains": {"M": [0., 1.], "X": [0., 1.]},
        "domain_scope": "Original active fractions; values outside these bounds are mathematical extrapolations",
        "versions": {p: version(p) for p in PACKAGES}, "samples": len(grid), "branches": []}
    for ucs, breaker, history, cue in probes:
        trains = branch_trains(ucs, [breaker], history, True, cue, reference)
        encoded = encode_protocol(path, trains)
        row = {"ucs": ucs, "breaker": breaker, "history": history, "cue": cue,
            "reset_trains": [asdict(t) for t in trains],
            "out_of_domain_resets": [{"start": t.start, "stop": t.stop,
                "values": {s: v for s, v in t.values.items() if s in ("M", "X") and not 0 <= v <= 1}}
                for t in trains if any(s in ("M", "X") and not 0 <= v <= 1 for s, v in t.values.items())],
            "encoded_sha256": hashlib.sha256(encoded.encode()).hexdigest(), "runs": []}
        for rtol, atol in [(1e-10, 1e-12), (1e-12, 1e-14), (1e-13, 1e-15)]:
            for engine in ("roadrunner", "copasi"):
                started = time.monotonic()
                result = native_run(encoded, info["observables"], grid, trains, engine, rtol, atol)
                row["runs"].append({"engine": engine, "rtol": rtol, "atol": atol,
                                   "seconds": time.monotonic()-started, **result})
                print(ucs, breaker, history, cue, engine, rtol,
                      result["completed"], result["terminal"], flush=True)
        report["branches"].append(row)
        (output/"report.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"results/catalog-breaking-goldbeter-diagnostic")
    args = parser.parse_args()
    logging.getLogger("basico.task_timecourse").setLevel(logging.CRITICAL)
    diagnose(args.output)
