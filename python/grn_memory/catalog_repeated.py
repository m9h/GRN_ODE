"""Six-pulse response histories with untreated and isolated-pulse controls.

All independently writable inputs are tested in both directions across all 35
models. Literal MATLAB pulse-mean codes are retained separately from contrasts
against a naive pulse at the same absolute time and with the same duration.
"""

from dataclasses import asdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import time

import numpy as np

from .catalog_memory import write_json
from .catalog_runner import context, fingerprint, implementation_hashes, run_catalog
from .catalog_validation import PACKAGES, comparison
from .native_protocols import ResetTrain, sample_times
from .timed_drives import encode_yoon_drives, yoon_trajectory


def pulse_schedule():
    now = 50.
    result = []
    for index in range(6):
        end = now + 50 + 10*index
        rest_end = end + 60 + 10*index
        result.append({"pulse": index+1, "start": now, "stop": end, "rest_stop": rest_end})
        now = rest_end
    return result


def trains_for(schedule, values):
    return [ResetTrain(p["start"], p["stop"], values, include_start=True, include_stop=True)
            for p in schedule]


def windows(schedule):
    result = {"baseline": (0., 50.)}
    for p in schedule:
        result[f'on_{p["pulse"]}'] = (p["start"], p["stop"])
        result[f'rest_{p["pulse"]}'] = (p["stop"], p["rest_stop"])
    return result


def summarize(trace, intervals):
    """Sample means and ranges, not quadrature estimates of continuous means."""
    result = {}
    for name, (start, stop) in intervals.items():
        if stop > float(trace.time.iloc[-1])+1e-8:
            continue
        values = trace.loc[(trace.time >= start) & (trace.time <= stop)].iloc[:, 1:]
        if values.empty or not np.isfinite(values.to_numpy()).all():
            raise ValueError("Non-finite or empty protocol window")
        result[name] = {symbol: {"mean": float(values[symbol].mean()), "minimum": float(values[symbol].min()),
                                 "maximum": float(values[symbol].max())} for symbol in values}
    return result


def matlab_codes(baseline, on):
    """Literal branch logic from Find_DrugRes_Sensitize_SLURM1.m.

The initial down-response code is 2, but a subsequent further decrease receives
1. Preserve this asymmetry for inspection rather than silently repairing it.
"""
    codes = [0]*len(on)
    if on[0] > 1.5*baseline:
        initial = 1
    elif on[0] <= baseline/1.5:
        initial = 2
    else:
        return codes
    codes[0] = initial
    for i in range(1, len(on)):
        if initial == 1:
            codes[i] = 1 if on[i] > 1.5*on[i-1] else 2 if on[i] <= on[i-1]/1.5 else 0
        else:
            codes[i] = 1 if on[i] <= on[i-1]/1.5 else 2 if on[i] > 1.5*on[i-1] else 0
    return codes


def increment_category(repeated_on, repeated_pre, naive_on, naive_pre, *, negative=False):
    """A resolved fold change in response increment, rather than absolute level."""
    if negative:
        return "negative_response_state"
    repeated = repeated_on-repeated_pre
    naive = naive_on-naive_pre
    resolution = 4*(1e-7+2e-5*max(map(abs, (repeated_on, repeated_pre, naive_on, naive_pre))))
    if abs(naive) <= resolution:
        return "unresolved" if abs(repeated) <= resolution else "response_after_history"
    if abs(repeated) <= resolution:
        return "attenuated_to_unresolved"
    if repeated*naive < 0:
        return "reversed"
    if abs(abs(repeated)-1.5*abs(naive)) <= resolution or abs(abs(repeated)-abs(naive)/1.5) <= resolution:
        return "threshold_unresolved"
    if abs(repeated) > 1.5*abs(naive):
        return "enhanced"
    if abs(repeated) < abs(naive)/1.5:
        return "attenuated"
    return "no_1.5fold_change"


def response_scores(repeated, naive, untreated, targets, stimulus, level):
    result = {}
    for symbol in targets:
        if symbol == stimulus:
            continue
        baseline = repeated["baseline"][symbol]["mean"]
        on = [repeated[f"on_{k}"][symbol]["mean"] for k in range(1, 7)]
        ranges = [v[symbol] for v in repeated.values()]
        input_ranges = [v[stimulus] for v in repeated.values()]
        varied = max(x["maximum"] for x in ranges) > min(x["minimum"] for x in ranges)
        varied_input = max(x["maximum"] for x in input_ranges) > min(x["minimum"] for x in input_ranges)
        eligible = level != 0 and varied and varied_input
        codes = matlab_codes(baseline, on) if eligible else [0]*6
        nonzero = [v for v in codes if v]
        rows = []
        for k in range(1, 7):
            pre = "baseline" if k == 1 else f"rest_{k-1}"
            own = repeated[f"on_{k}"][symbol]
            # Pulse 1 has exactly the same history in both arms.
            isolated = repeated if k == 1 else naive[str(k)]
            pre_mean = repeated[pre][symbol]["mean"]
            naive_on = isolated[f"on_{k}"][symbol]["mean"]
            naive_pre = isolated[pre][symbol]["mean"]
            relevant = [own, repeated[pre][symbol], isolated[f"on_{k}"][symbol], isolated[pre][symbol]]
            threshold = 1e-7+2e-5*max(abs(v["maximum"]) for v in relevant)
            negative = any(v["minimum"] < -threshold for v in relevant)
            rows.append({"pulse": k, "pre_mean": pre_mean, "on_mean": own["mean"],
                         "increment": own["mean"]-pre_mean,
                         "untreated_on_mean": untreated[f"on_{k}"][symbol]["mean"],
                         "naive_on_mean": naive_on, "naive_pre_mean": naive_pre,
                         "naive_increment": naive_on-naive_pre,
                         "history_effect_on_level": own["mean"]-naive_on,
                         "history_effect_on_increment": own["mean"]-pre_mean-naive_on+naive_pre,
                         "negative_response_values": negative,
                         "increment_category": increment_category(own["mean"], pre_mean, naive_on, naive_pre,
                                                                    negative=negative)})
        result[symbol] = {"matlab_eligible": eligible, "matlab_pulse_codes": codes,
                          "matlab_resistance": len(nonzero)>1 and nonzero[0] != nonzero[-1],
                          "matlab_sensitization": len(nonzero)>1 and len(set(nonzero)) == 1,
                          "pulses": rows, "final_increment_category": rows[-1]["increment_category"]}
    return result


def run_model(entry, args):
    path, reference, targets, excluded, trajectory = context(entry)
    engines = reference["engines"]
    integration = deepcopy(reference["configuration"]["integration_settings"])
    case_overrides = {}
    encoding = None
    if entry["network"] == 26:
        integration = {engine: {"rtol": 1e-12, "atol": 1e-18} for engine in engines}
        trajectory = yoon_trajectory
        encoding = {"method": "equivalent timed g1/g2 switches as events for t >= 0",
                    "sha256": hashlib.sha256(encode_yoon_drives(path).encode("utf-8")).hexdigest()}
    if entry["network"] == 35:
        case_overrides = {"HPrPIIA__down": {"copasi": {"rtol": 1e-7, "atol": 1e-9}}}
    schedule = pulse_schedule()
    intervals = windows(schedule)
    # Long absolute times magnify event-root rounding at very fast transients.
    # Record an explicit 1e-5 offset (0.1% of dt), shared by every control arm.
    all_times = sample_times(1010., args.sample_dt, trains_for(schedule, {}),
                             post_reset_offset=args.post_reset_offset)
    config = {"schedule": schedule, "dt": args.sample_dt, "reset_interval": .1, "include_onset": True,
              "include_withdrawal": True, "post_reset_offset": args.post_reset_offset,
              "summary_statistic": "arithmetic sample mean on the recorded grid; not a continuous-time integral",
              "calibration": "complete untreated trajectory, t=0..1010; strictly positive minimum",
              "integration_settings": integration, "comparison_rtol": 2e-5, "comparison_atol": 1e-7,
              "case_integration_overrides": case_overrides, "timed_drive_encoding": encoding,
              "controls": "untreated, and each later pulse in isolation at identical time/duration",
              "input_scale_up": 100., "input_scale_down": .01}
    files = ["catalog_repeated.py", "catalog_runner.py", "catalog_memory.py", "catalog_validation.py",
             "native_protocols.py", "delay_protocols.py", "scheper_delay.py", "simulation.py", "analysis.py", "timed_drives.py"]
    metadata = {"configuration": config, "model_sha256": reference["model_sha256"],
                "reference_fingerprint": reference["fingerprint"], "implementation_sha256": implementation_hashes(files),
                "versions": {p: version(p) for p in PACKAGES}}
    if "jitcdde" in engines:
        metadata["versions"].update({p: version(p) for p in ("scipy", "jitcdde", "symengine")})
        config.update({"jitcdde_step": .001, "refined_step": .0005, "jump_width": 1e-9,
                       "refined_jump_width": 5e-10, "history": "M=P=1 for t<0, retained across all pulses"})
    signature = fingerprint(metadata)
    destination = args.output/f'{entry["biomodel_id"]}.json'
    report = {**entry, "name": reference["name"], **metadata, "fingerprint": signature,
              "engines": engines, "targets": targets, "excluded_species": excluded,
              "expected_cases": len(targets)*2, "cases": {}, "status": "running",
              "started_at": datetime.now(timezone.utc).isoformat()}
    if args.resume and destination.exists():
        saved = json.loads(destination.read_text())
        if saved.get("fingerprint") == signature:
            report = saved
    report["status"] = "running"
    write_json(destination, report)
    control = {e: trajectory(path, all_times, [], e, **integration[e]) for e in engines}
    report["control_comparison"] = comparison(*control.values())
    report["control_windows"] = {e: summarize(t, intervals) for e,t in control.items()}
    if encoding:
        from .native_protocols import protocol_trajectory
        report["encoding_control_comparisons"] = {
            e: comparison(control[e], protocol_trajectory(path, all_times, [], e,
                **reference["configuration"]["integration_settings"][e])) for e in engines}
    reference_control = control[engines[0]]
    levels = {}
    for symbol in targets:
        positive = reference_control.loc[reference_control[symbol] > 0, symbol]
        maximum = float(reference_control[symbol].max())
        minimum = float(positive.min()) if len(positive) else 0.
        levels[symbol] = {"up": max(0., maximum)*100, "down": minimum/100,
                          "maximum": maximum, "minimum_positive": minimum,
                          "minimum_raw": float(reference_control[symbol].min())}
    report["calibration"] = levels
    keys = [symbol+"__"+direction for symbol in targets for direction in ("up", "down")]
    if args.case:
        if set(args.case)-set(keys):
            raise ValueError("Unknown repeated-input case key")
        keys = [key for key in keys if key in args.case]
    if args.limit_cases:
        keys = keys[:args.limit_cases]

    def run_branch(trains, times, relevant, settings):
        traces = {e: trajectory(path, times, trains, e, **settings[e]) for e in engines}
        record = {"comparison": comparison(*traces.values()), "sample_count": len(times),
                  "reset_trains": [asdict(t) for t in trains],
                  "windows": {e: summarize(t, relevant) for e,t in traces.items()}}
        record["passed"] = record["comparison"]["passed"]
        if "jitcdde" in engines:
            refined = trajectory(path, times, trains, "jitcdde", step=.0005, jump_width=5e-10)
            record["refinement"] = {"versus_method_of_steps": comparison(traces[engines[0]], refined),
                                    "versus_original_step": comparison(traces[engines[1]], refined)}
            record["passed"] &= all(c["passed"] for c in record["refinement"].values())
        return record

    for key in keys:
        if args.resume and report["cases"].get(key, {}).get("status") == "passed":
            continue
        start = time.monotonic()
        symbol, direction = key.rsplit("__", 1)
        level = levels[symbol][direction]
        settings = {**integration, **case_overrides.get(key, {})}
        case = {"input": symbol, "direction": direction, "level": level, "status": "failed",
                "zero_level": level == 0, "branches": {}, "integration_settings": settings}
        try:
            case["branches"]["repeated"] = run_branch(trains_for(schedule, {symbol: level}), all_times, intervals, settings)
            for pulse in schedule[1:]:
                k = pulse["pulse"]
                needed = {f"rest_{k-1}": intervals[f"rest_{k-1}"], f"on_{k}": intervals[f"on_{k}"],
                          f"rest_{k}": intervals[f"rest_{k}"]}
                times = all_times[all_times <= pulse["rest_stop"]]
                case["branches"][f"naive_{k}"] = run_branch(trains_for([pulse], {symbol: level}), times, needed, settings)
            case["scores"] = {e: response_scores(case["branches"]["repeated"]["windows"][e],
                {str(k): case["branches"][f"naive_{k}"]["windows"][e] for k in range(2,7)},
                report["control_windows"][e], targets, symbol, level) for e in engines}
            differences = {}
            raw_differences = {}
            for response in case["scores"][engines[0]]:
                a,b = (case["scores"][e][response] for e in engines)
                for field in ("matlab_pulse_codes", "matlab_resistance", "matlab_sensitization"):
                    if a[field] != b[field]:
                        raw_differences.setdefault(response, []).append(field)
                for k,(x,y) in enumerate(zip(a["pulses"], b["pulses"]), 1):
                    if x["increment_category"] != y["increment_category"]:
                        differences.setdefault(response, []).append(k)
            case["controlled_classification_disagreements"] = differences
            case["raw_matlab_disagreements"] = raw_differences
            case["status"] = "passed" if all(b["passed"] for b in case["branches"].values()) and not differences else "mismatch"
        except Exception as exc:
            case["error"] = f"{type(exc).__name__}: {exc}"
        case["elapsed_seconds"] = time.monotonic()-start
        report["cases"][key] = case
        write_json(destination, report)
        print(f'{entry["network"]:02d} {key}: {case["status"]} {case.get("error", "")}', flush=True)
    report["evaluated_cases"] = len(report["cases"])
    report["passed_cases"] = sum(c["status"] == "passed" for c in report["cases"].values())
    report["status"] = ("passed" if report["passed_cases"] == report["expected_cases"]
                        and report["control_comparison"]["passed"]
                        and all(c["passed"] for c in report.get("encoding_control_comparisons", {}).values())
                        else "incomplete_or_failed")
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(destination, report)
    return report


if __name__ == "__main__":
    run_catalog("catalog_repeated", run_model, __doc__)
