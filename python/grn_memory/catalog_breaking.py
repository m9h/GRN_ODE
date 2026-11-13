"""Three-trial search for interventions on acquired response histories.

The MATLAB sequence is B, UCS, B, UCS, C, UCS, each exposure and following
rest lasting 100 native time units. Later trials are conditional. All histories
start at native time zero and preserve the six-pulse training trajectory.
"""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import time
from collections import Counter

from .breaking_scores import trial_scores, classification_key, remaining_responses
from .catalog_archive import EvidenceStore
from .catalog_memory import write_json
from .catalog_repeated import pulse_schedule, trains_for, summarize
from .catalog_runner import ROOT, context, fingerprint, implementation_hashes, run_catalog
from .catalog_validation import PACKAGES, comparison
from .native_protocols import ResetTrain, sample_times
from .protocol_retries import integrate_engines
from .timed_drives import encode_yoon_drives, yoon_trajectory


def candidate_plans(reference):
    """Union of literal MATLAB resistance/sensitization eligibility in both engines."""
    result = {}
    engines = reference["engines"]
    cases = reference["cases"]
    for u, case in cases.items():
        if case["status"] != "passed":
            raise ValueError("Breaking requires a complete validated repeated-input reference")
        eligible = {}
        for response in case["scores"][engines[0]]:
            source = {}
            for e in engines:
                score = case["scores"][e][response]
                codes = [code for code in score["matlab_pulse_codes"] if code]
                source[e] = {"eligible":bool(score["matlab_resistance"] or score["matlab_sensitization"]),
                             "resistance":score["matlab_resistance"], "sensitization":score["matlab_sensitization"],
                             "last_code":codes[-1] if codes else None}
            if any(s["eligible"] for s in source.values()):
                eligible[response] = source
        for b, breaker in cases.items():
            if breaker["input"] == case["input"] or breaker["level"] == 0:
                continue
            responses = {r:s for r,s in eligible.items() if r != breaker["input"]}
            if responses:
                result[u+"--"+b] = {"ucs":u, "breaker":b, "responses":responses}
    return dict(sorted(result.items()))


def trial_windows(trial):
    result = {"prefix":(0.,1010.)}
    for k in range(1,trial+1):
        start = 1010.+400*(k-1)
        result.update({f"intervention_{k}":(start,start+100), f"pre_{k}":(start+100,start+200),
                       f"cue_{k}":(start+200,start+300), f"post_{k}":(start+300,start+400)})
    return result


def branch_trains(ucs, breakers, history, breaking, cue, reference):
    """All prior rechallenges are retained, including in the current-cue sham."""
    def values(key):
        case = reference["cases"][key]
        return {case["input"]:case["level"]}
    trains = trains_for(pulse_schedule(),values(ucs)) if history else []
    for k, breaker in enumerate(breakers):
        start = 1010.+400*k
        if breaking:
            trains.append(ResetTrain(start,start+100,values(breaker)))
        if k < len(breakers)-1 or cue:
            trains.append(ResetTrain(start+200,start+300,values(ucs)))
    return sorted(trains,key=lambda train:train.start)


def next_breakers(plan, remaining, reference):
    """The third breaker has a fourth distinct identity for each response."""
    original = reference["cases"][plan["ucs"]]["input"]
    first = reference["cases"][plan["breaker"]]["input"]
    result = {}
    for key, case in reference["cases"].items():
        if case["input"] in (original,first) or case["level"] == 0:
            continue
        responses = [r for r in remaining if r != case["input"]]
        if responses:
            result[key] = responses
    return result


def run_model(entry,args):
    path, single, targets, excluded, trajectory = context(entry)
    source_path = ROOT/"results/catalog-repeated"/f'{entry["biomodel_id"]}.json'
    reference = json.loads(source_path.read_text())
    if reference["status"] != "passed" or reference["model_sha256"] != single["model_sha256"]:
        raise ValueError("Matching validated repeated-input results are required")
    if reference["targets"] != targets:
        raise ValueError("Independent state inventory changed")
    engines = reference["engines"]
    plans = candidate_plans(reference)
    integration = deepcopy(reference["configuration"]["integration_settings"])
    overrides = deepcopy(reference["configuration"]["case_integration_overrides"])
    if entry["network"] == 4:
        # The full-horizon Goldbeter explicit-pool diagnostic confirms these
        # requests and a further refinement on all eight original mismatches.
        # Calibration, reset timing, conditional search and acceptance stay fixed.
        integration = {engine: {"rtol": 1e-13, "atol": 1e-15} for engine in engines}
    if entry["network"] == 12:
        # All twelve original Leloup mismatches pass both native cross-engine
        # comparisons and each engine's tighter refinement over the full horizon.
        # Recompute every case and conditional continuation at the supported
        # tighter request; the original completed evidence remains separate.
        integration = {engine: {"rtol": 1e-13, "atol": 1e-15} for engine in engines}
    fallbacks = {"copasi":{"rtol":1e-7,"atol":1e-9}} if entry["network"] == 35 else {}
    encoding = None
    if entry["network"] == 26:
        trajectory = yoon_trajectory
        encoding = {"method":"equivalent timed g1/g2 switches as events for t >= 0",
                    "sha256":hashlib.sha256(encode_yoon_drives(path).encode()).hexdigest()}
    possible = trains_for(pulse_schedule(),{})
    possible += [ResetTrain(start,start+100,{}) for start in (1010.,1210.,1410.,1610.,1810.,2010.)]
    all_times = sample_times(2210.,args.sample_dt,possible,post_reset_offset=args.post_reset_offset)
    config = {"dt":args.sample_dt, "post_reset_offset":args.post_reset_offset,
              "prefix":pulse_schedule(), "trials":trial_windows(3), "reset_interval":.1,
              "prefix_endpoint_resets":True, "later_endpoint_resets":False,
              "later_resets_per_exposure":999, "calibration":"unchanged repeated-screen levels, untreated t=0..1010",
              "candidate_selection":"union of both engines' literal MATLAB resistance/sensitization eligibility",
              "continuation":"continue if any eligible engine has not passed the raw MATLAB reversal test",
              "third_trial":"new breaker identity excluding UCS, first breaker and response; both nonzero levels",
              "zero_breaker_policy":"exclude as in MATLAB; record candidate count before simulation",
              "integration_settings":integration, "case_integration_overrides":overrides,
              "integration_error_fallbacks":fallbacks,
              "retry_policy":"one declared fallback after solver exception only; no retry after a completed numerical mismatch",
              "timed_drive_encoding":encoding, "comparison_rtol":2e-5, "comparison_atol":1e-7,
              "candidate_plan_sha256":fingerprint(plans),
              "summary_statistic":"arithmetic sample means and ranges; not continuous-time integrals",
              "controls":"prior history x breaker sequence x final rechallenge, all eight combinations"}
    files = ["catalog_breaking.py","breaking_scores.py","catalog_archive.py","paired_scores.py",
             "catalog_repeated.py","catalog_runner.py","catalog_memory.py","catalog_validation.py",
             "native_protocols.py","delay_protocols.py","scheper_delay.py","simulation.py","analysis.py","timed_drives.py",
             "protocol_retries.py"]
    metadata = {"configuration":config,"model_sha256":reference["model_sha256"],
                "reference_fingerprint":reference["fingerprint"],
                "reference_file_sha256":hashlib.sha256(source_path.read_bytes()).hexdigest(),
                "implementation_sha256":implementation_hashes(files),"versions":{p:version(p) for p in PACKAGES}}
    if "jitcdde" in engines:
        metadata["versions"].update({p:version(p) for p in ("scipy","jitcdde","symengine")})
        config.update({"jitcdde_step":.001,"refined_step":.0005,"jump_width":1e-9,
                       "refined_jump_width":5e-10,"history":"M=P=1 for t<0, preserved through all trials"})
    signature = fingerprint(metadata)
    destination = args.output/f'{entry["biomodel_id"]}.json'
    store = EvidenceStore(args.output,entry["biomodel_id"],signature,args.resume)
    report = {**entry,"name":reference["name"],**metadata,"fingerprint":signature,
              "targets":targets,"excluded_species":excluded,"engines":engines,
              "expected_cases":len(plans),"expected_initial_response_assessments":sum(len(p["responses"]) for p in plans.values()),
              "cases":{},"status":"running","no_candidates":not plans,
              "started_at":datetime.now(timezone.utc).isoformat()}
    write_json(destination,report)

    def branch(trains,trial,settings):
        stop = 1010.+400*trial
        spec = {"reset_trains":[asdict(t) for t in trains],"stop":stop,"integration_settings":settings}
        key = fingerprint(spec)
        cached = store.get("branches",key,passed_only=key not in store.used["branches"])
        if cached is not None:
            return cached
        start = time.monotonic()
        times = all_times[all_times <= stop]
        record = {"specification":spec,"sample_count":len(times),"passed":False}
        try:
            traces = integrate_engines(trajectory,path,times,trains,engines,settings,fallbacks,record)
            record["comparison"] = comparison(*traces.values())
            record["windows"] = {e:summarize(t,trial_windows(trial)) for e,t in traces.items()}
            record["passed"] = record["comparison"]["passed"]
            if "jitcdde" in engines:
                refined = trajectory(path,times,trains,"jitcdde",step=.0005,jump_width=5e-10)
                record["refinement"] = {"versus_method_of_steps":comparison(traces[engines[0]],refined),
                                        "versus_original_step":comparison(traces[engines[1]],refined)}
                record["passed"] &= all(c["passed"] for c in record["refinement"].values())
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        record["elapsed_seconds"] = time.monotonic()-start
        print(f'{entry["network"]:02d} branch {key[:12]}: {record["passed"]} {record.get("error", "")}',flush=True)
        return store.put("branches",key,record)

    control = branch([],3,integration)
    report["control_comparison"] = control.get("comparison",{"passed":False,"error":control.get("error")})
    encoding_passed = True
    if encoding:
        from .native_protocols import protocol_trajectory
        report["encoding_control_comparisons"] = {
            e:comparison(trajectory(path,all_times,[],e,**integration[e]),
                         protocol_trajectory(path,all_times,[],e,**single["configuration"]["integration_settings"][e]))
            for e in engines}
        encoding_passed = all(c["passed"] for c in report["encoding_control_comparisons"].values())

    def evaluate_trial(plan,breakers,responses):
        k = len(breakers)
        settings = {**integration,**overrides.get(plan["ucs"],{})}
        branches = {}
        for name,history,breaking in (("none",False,False),("history",True,False),
                                     ("breaker",False,True),("history_breaker",True,True)):
            for cue in (False,True):
                trains = branch_trains(plan["ucs"],breakers,history,breaking,cue,reference)
                branches[name+("_cue" if cue else "_sham")] = branch(trains,k,settings)
        record = {"trial":k,"breakers":breakers,"responses":responses,
                  "branches":{role:b["record_id"] for role,b in branches.items()},"passed":False}
        if not all("windows" in b for b in branches.values()):
            record["failed_branches"] = {role:b.get("error") for role,b in branches.items() if "windows" not in b}
            return record
        record["scores"] = {e:trial_scores(branches,e,responses,plan["responses"],k) for e in engines}
        record["controlled_classification_disagreements"] = [r for r in responses if
            classification_key(record["scores"][engines[0]][r]) != classification_key(record["scores"][engines[1]][r])]
        # Audit categorical raw disagreement, not ordinary differences in means.
        fields = ("eligible","resistance","sensitization","last_code","break_direction")
        record["raw_matlab_disagreements"] = [r for r in responses if any(
            record["scores"][engines[0]][r]["matlab"][f] != record["scores"][engines[1]][r]["matlab"][f] for f in fields)]
        record["remaining_responses"] = remaining_responses(record["scores"],responses,engines)
        record["passed"] = all(b["passed"] for b in branches.values()) and not record["controlled_classification_disagreements"]
        return record

    keys = list(plans)
    if args.case:
        if set(args.case)-set(keys):
            raise ValueError("Unknown initial breaking case key")
        keys = [key for key in keys if key in args.case]
    if args.limit_cases:
        keys = keys[:args.limit_cases]
    for key in keys:
        plan = plans[key]
        case_id = fingerprint(plan)
        case = store.get("cases",case_id)
        if case is not None:
            for trial in case["trials"].values():
                for branch_key in trial["branches"].values():
                    if store.get("branches",branch_key) is None:
                        raise ValueError("Passed case checkpoint is missing validated branch evidence")
        else:
            start = time.monotonic()
            case = {**plan,"case_key":key,"trials":{},"passed":False}
            responses = list(plan["responses"])
            first = evaluate_trial(plan,[plan["breaker"]],responses)
            case["trials"]["first"] = first
            remaining = first.get("remaining_responses")
            if remaining:
                second = evaluate_trial(plan,[plan["breaker"]]*2,remaining)
                case["trials"]["second"] = second
                remaining = second.get("remaining_responses")
                if remaining:
                    thirds = next_breakers(plan,remaining,reference)
                    case["expected_third_trials"] = {k:v for k,v in thirds.items()}
                    case["responses_without_available_third_breaker"] = [r for r in remaining if not any(r in v for v in thirds.values())]
                    for third, selected in thirds.items():
                        case["trials"]["third__"+third] = evaluate_trial(plan,[plan["breaker"],plan["breaker"],third],selected)
            case["passed"] = all(t["passed"] for t in case["trials"].values())
            case["elapsed_seconds"] = time.monotonic()-start
            case = store.put("cases",case_id,case)
        categories = Counter(s["category"] for t in case["trials"].values()
                             for s in t.get("scores",{}).get(engines[0],{}).values())
        report["cases"][key] = {"record_id":case_id,"status":"passed" if case["passed"] else "mismatch",
            "initial_response_assessments":len(plan["responses"]),"evaluated_trials":len(case["trials"]),
            "evaluated_response_trials":sum(len(t["responses"]) for t in case["trials"].values()),
            "controlled_categories":dict(categories),
            "raw_disagreeing_response_trials":sum(len(t.get("raw_matlab_disagreements",[])) for t in case["trials"].values())}
        write_json(destination,report)
        print(f'{entry["network"]:02d} {key}: {report["cases"][key]["status"]} ({len(case["trials"])} trials)',flush=True)
    report["evidence_archives"] = store.publish()
    report["evaluated_cases"] = len(report["cases"])
    report["passed_cases"] = sum(c["status"] == "passed" for c in report["cases"].values())
    report["evaluated_unique_branches"] = len(store.used["branches"])
    report["solver_retry_branches"] = sum(any(len(a)>1 for a in
        store.get("branches",key,passed_only=False).get("solver_attempts",{}).values())
        for key in store.used["branches"])
    report["status"] = ("passed" if report["passed_cases"] == len(plans) and control["passed"]
                        and encoding_passed else "incomplete_or_failed")
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(destination,report)
    return report


def main():
    run_catalog("catalog_breaking",run_model,__doc__)


if __name__ == "__main__":
    main()
