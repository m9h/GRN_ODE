"""Catalog-wide paired exposure, transfer, delayed cue and recall experiments.

Validated single-input results select UCS/CS/response triples. All four training
histories are tested with a sham and two separate cue times. Histories are
deduplicated by intervention schedule, without restarting clocks or states.
"""

from dataclasses import asdict
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import time

from .catalog_memory import write_json
from .catalog_repeated import summarize
from .catalog_runner import context, fingerprint, implementation_hashes, run_catalog
from .catalog_validation import ROOT, PACKAGES, comparison
from .native_protocols import ResetTrain, sample_times
from .paired_scores import response_score, classification_key
from .protocol_retries import integrate_engines
from .timed_drives import encode_yoon_drives, yoon_trajectory


WINDOWS = {"baseline": (0.,50.), "train": (50.,100.), "wash": (100.,150.),
           "probe": (150.,200.), "postprobe": (200.,250.), "late": (250.,300.)}


def candidate_plans(reference):
    """Exhaust all distinct UCS, CS and response identities in the reference.

UCS: both engines resolve the training effect and agree on a nonzero twofold
response. Candidate CS: neither engine establishes a resolved twofold response.
An unresolved small effect is therefore a candidate, not proven neutrality.
"""
    result = {}
    engines = reference["engines"]
    cases = reference["cases"]
    for response in reference["targets"]:
        ucs, cs = [], []
        for key, case in cases.items():
            if case["status"] != "passed":
                raise ValueError("Candidate selection requires every reference case to pass")
            if response == case["input"]:
                continue
            scores = [case["scores"][e][response] for e in engines]
            directions = [s["response_direction"] if s["training_effect_resolved"] else 0 for s in scores]
            if directions[0] != 0 and all(d == directions[0] for d in directions):
                ucs.append(key)
            elif all(d == 0 for d in directions):
                cs.append(key)
        for u in ucs:
            for c in cs:
                if cases[u]["input"] == cases[c]["input"]:
                    continue
                key = u+"--"+c
                result.setdefault(key, {"ucs": u, "cs": c, "responses": []})["responses"].append(response)
    return dict(sorted(result.items()))


def branch_spec(training=(), probe=None, start=None):
    return {"training": sorted(training), "probe": probe, "probe_start": start if probe else None}


def branch_id(spec):
    return fingerprint(spec)


def case_branches(plan):
    histories = {"none": (), "ucs": (plan["ucs"],), "cs": (plan["cs"],),
                 "paired": (plan["ucs"], plan["cs"])}
    result = {}
    for h, training in histories.items():
        result[h+"_sham"] = branch_spec(training)
        result[h+"_normal"] = branch_spec(training, plan["cs"], 150.)
        result[h+"_delayed"] = branch_spec(training, plan["cs"], 200.)
    return result


def reset_trains(spec, reference):
    def values(keys):
        return {reference["cases"][key]["input"]: reference["cases"][key]["level"] for key in keys}
    trains = []
    if spec["training"]:
        if len(values(spec["training"])) != len(spec["training"]):
            raise ValueError("Training inputs must refer to distinct independent symbols")
        trains.append(ResetTrain(50., 100., values(spec["training"])))
    if spec["probe"]:
        start = spec["probe_start"]
        trains.append(ResetTrain(start, start+50., values([spec["probe"]])))
    return trains


def write_gzip_json(path, value):
    temporary = path.with_suffix(".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as stream:
        json.dump(value, stream, allow_nan=False, separators=(",", ":"))
        stream.write("\n")
    temporary.replace(path)


def run_model(entry, args):
    path, reference, targets, excluded, trajectory = context(entry)
    engines = reference["engines"]
    plans = candidate_plans(reference)
    specs = {branch_id(spec): spec for plan in plans.values() for spec in case_branches(plan).values()}
    specs[branch_id(branch_spec())] = branch_spec()
    integration = deepcopy(reference["configuration"]["integration_settings"])
    fallbacks = {"copasi": {"rtol": 1e-11, "atol": 1e-13}} if entry["network"] == 25 else {}
    encoding = None
    if entry["network"] == 26:
        integration = {e: {"rtol": 1e-12, "atol": 1e-18} for e in engines}
        trajectory = yoon_trajectory
        encoding = {"method": "equivalent timed g1/g2 switches as events for t >= 0",
                    "sha256": hashlib.sha256(encode_yoon_drives(path).encode("utf-8")).hexdigest()}
    grid_trains = [ResetTrain(start, start+50., {}) for start in (50.,150.,200.)]
    times = sample_times(300., args.sample_dt, grid_trains, post_reset_offset=args.post_reset_offset)
    config = {"windows": WINDOWS, "dt": args.sample_dt, "post_reset_offset": args.post_reset_offset,
              "reset_interval": .1, "include_onset": False, "include_withdrawal": False,
              "resets_per_training_or_probe": 499,
              "calibration": "unchanged single-input reference levels from native t=0..50",
              "summary_statistic": "arithmetic sample mean; not a continuous-time integral",
              "candidate_selection": "resolved twofold UCS in both engines; no resolved twofold CS in either; three distinct identities",
              "histories": ["none", "ucs", "cs", "paired"], "probe_starts": [150.,200.],
              "integration_settings": integration, "comparison_rtol": 2e-5, "comparison_atol": 1e-7,
              "integration_error_fallbacks": fallbacks,
              "retry_policy": "one declared fallback after solver exception only; no retry after a completed numerical mismatch",
              "timed_drive_encoding": encoding, "candidate_plan_sha256": fingerprint(plans),
              "negative_response_policy": "retain numerical result but exclude controlled learning interpretation"}
    files = ["catalog_paired.py", "paired_scores.py", "catalog_repeated.py", "catalog_runner.py",
             "catalog_memory.py", "catalog_validation.py", "native_protocols.py", "delay_protocols.py",
             "scheper_delay.py", "simulation.py", "analysis.py", "timed_drives.py", "protocol_retries.py"]
    metadata = {"configuration": config, "model_sha256": reference["model_sha256"],
                "reference_fingerprint": reference["fingerprint"],
                "reference_file_sha256": hashlib.sha256((ROOT/"results/catalog-memory"/f'{entry["biomodel_id"]}.json').read_bytes()).hexdigest(),
                "implementation_sha256": implementation_hashes(files), "versions": {p:version(p) for p in PACKAGES}}
    if "jitcdde" in engines:
        metadata["versions"].update({p:version(p) for p in ("scipy", "jitcdde", "symengine")})
        config.update({"jitcdde_step": .001, "refined_step": .0005, "jump_width": 1e-9,
                       "refined_jump_width": 5e-10, "history": "M=P=1 for t<0; retained across every reset"})
    signature = fingerprint(metadata)
    destination = args.output/f'{entry["biomodel_id"]}.json'
    cache = args.output/".branches"/entry["biomodel_id"]/signature
    cache.mkdir(parents=True, exist_ok=True)
    report = {**entry, "name": reference["name"], **metadata, "fingerprint": signature,
              "targets": targets, "excluded_species": excluded, "engines": engines,
              "expected_cases": len(plans), "expected_response_assessments": sum(len(p["responses"]) for p in plans.values()),
              "expected_unique_branches": len(specs), "cases": {}, "status": "running",
              "no_candidates": not plans, "started_at": datetime.now(timezone.utc).isoformat()}
    if args.resume and destination.exists():
        saved = json.loads(destination.read_text())
        if saved.get("fingerprint") == signature:
            report = saved
    report["status"] = "running"
    write_json(destination, report)
    records = {}

    def get_branch(spec):
        key = branch_id(spec)
        if key in records:
            return records[key]
        cached = cache/(key+".json.gz")
        if args.resume and cached.exists():
            with gzip.open(cached, "rt", encoding="utf-8") as stream:
                saved = json.load(stream)
            if saved.get("fingerprint") == signature and saved.get("specification") == spec and saved.get("passed"):
                records[key] = saved
                return saved
        start = time.monotonic()
        trains = reset_trains(spec, reference)
        record = {"branch_id": key, "fingerprint": signature, "specification": spec,
                  "reset_trains": [asdict(t) for t in trains], "sample_count": len(times), "passed": False}
        try:
            traces = integrate_engines(trajectory, path, times, trains, engines, integration, fallbacks, record)
            record["comparison"] = comparison(*traces.values())
            record["windows"] = {e:summarize(trace, WINDOWS) for e,trace in traces.items()}
            record["passed"] = record["comparison"]["passed"]
            if "jitcdde" in engines:
                refined = trajectory(path, times, trains, "jitcdde", step=.0005, jump_width=5e-10)
                record["refinement"] = {"versus_method_of_steps": comparison(traces[engines[0]], refined),
                                        "versus_original_step": comparison(traces[engines[1]], refined)}
                record["passed"] &= all(c["passed"] for c in record["refinement"].values())
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        record["elapsed_seconds"] = time.monotonic()-start
        write_gzip_json(cached, record)
        records[key] = record
        print(f'{entry["network"]:02d} branch {key[:12]}: {record["passed"]} {record.get("error", "")}', flush=True)
        return record

    untreated = get_branch(branch_spec())
    report["control_comparison"] = untreated.get("comparison", {"passed": False, "error": untreated.get("error")})
    encoding_passed = True
    if encoding:
        from .native_protocols import protocol_trajectory
        report["encoding_control_comparisons"] = {
            e:comparison(trajectory(path, times, [], e, **integration[e]),
                         protocol_trajectory(path, times, [], e, **reference["configuration"]["integration_settings"][e]))
            for e in engines}
        encoding_passed = all(c["passed"] for c in report["encoding_control_comparisons"].values())
    keys = list(plans)
    if args.case:
        if set(args.case)-set(keys):
            raise ValueError("Unknown paired-input case key")
        keys = [key for key in keys if key in args.case]
    if args.limit_cases:
        keys = keys[:args.limit_cases]
    for key in keys:
        start = time.monotonic()
        plan = plans[key]
        branches = {role:get_branch(spec) for role,spec in case_branches(plan).items()}
        case = {**plan, "status": "failed", "branches": {role:b["branch_id"] for role,b in branches.items()},
                "levels": {k:reference["cases"][k]["level"] for k in (plan["ucs"],plan["cs"])}}
        if all("windows" in b for b in branches.values()):
            case["scores"] = {e:{r:response_score(branches,e,r) for r in plan["responses"]} for e in engines}
            case["controlled_classification_disagreements"] = [r for r in plan["responses"] if
                classification_key(case["scores"][engines[0]][r]) != classification_key(case["scores"][engines[1]][r])]
            case["paper_like_disagreements"] = {r:[k for k,v in case["scores"][engines[0]][r]["paper_like"].items()
                if v != case["scores"][engines[1]][r]["paper_like"][k]] for r in plan["responses"]}
            case["paper_like_disagreements"] = {r:v for r,v in case["paper_like_disagreements"].items() if v}
            case["status"] = ("passed" if all(b["passed"] for b in branches.values()) and
                              not case["controlled_classification_disagreements"] else "mismatch")
        else:
            case["failed_branches"] = {role:b.get("error") for role,b in branches.items() if "windows" not in b}
        case["elapsed_seconds"] = time.monotonic()-start
        report["cases"][key] = case
        write_json(destination, report)
        print(f'{entry["network"]:02d} {key}: {case["status"]}', flush=True)

    # Publish one compressed, line-delimited archive per model, while the small
    # branch cache permits restart after interruptions. Hash it from the report.
    archive = args.output/f'{entry["biomodel_id"]}-branches.jsonl.gz'
    temporary = archive.with_suffix(".tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as stream:
            for key in sorted(records):
                stream.write((json.dumps(records[key], allow_nan=False, separators=(",", ":"))+"\n").encode())
    temporary.replace(archive)
    report["branch_archive"] = {"file": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                                "format": "gzip JSON Lines, one complete branch record per line"}
    report["evaluated_cases"] = len(report["cases"])
    report["passed_cases"] = sum(c["status"] == "passed" for c in report["cases"].values())
    report["evaluated_unique_branches"] = len(records)
    report["passed_unique_branches"] = sum(b["passed"] for b in records.values())
    report["status"] = ("passed" if report["passed_cases"] == len(plans) and len(records) == len(specs)
                        and all(b["passed"] for b in records.values()) and encoding_passed else "incomplete_or_failed")
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(destination, report)
    return report


def main():
    run_catalog("catalog_paired", run_model, __doc__)


if __name__ == "__main__":
    main()
