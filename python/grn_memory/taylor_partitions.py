"""Resume one complete original failed paired branch, or its baseline.

Partitioning changes scheduling only. Every selected branch keeps its original
300-unit protocol, reset schedule, 30,001 observations and acceptance thresholds.
These diagnostics do not recover cases whose other controls are uncomputed.
"""

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import gzip
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import time

import numpy as np
import pandas as pd

from .catalog_memory import write_json
from .catalog_validation import comparison, inspect_model
from .native_protocols import ResetTrain, protocol_trajectory, sample_times
from .taylor_checkpoints import TaylorCheckpointStop, signature

ROOT = Path(__file__).resolve().parents[1]
REQUESTS = {"taylor128": {"precision": 128, "tolerance": "1e-30"},
            "taylor192": {"precision": 192, "tolerance": "1e-45"},
            "roadrunner": {"rtol": 1e-13, "atol": 1e-15}}
ACCEPTANCE = {"rtol": 2e-5, "atol": 1e-7}
PAIRS = (("taylor128", "taylor192"), ("taylor128", "roadrunner"), ("taylor192", "roadrunner"))
SOURCES = ("grn_memory/taylor_partitions.py", "grn_memory/taylor_reference.py",
           "grn_memory/taylor_checkpoints.py", "grn_memory/native_protocols.py",
           "grn_memory/catalog_validation.py", "grn_memory/catalog_memory.py",
           "scripts/run_taylor_checkpoint_partition.py")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def problem(model, index, count):
    """Reconstruct the entire failure inventory before selecting one branch."""
    mid = f"BIOMD{model:010d}"
    path = ROOT / "models" / (mid + ".xml")
    source = ROOT / "results/catalog-paired" / (mid + ".json")
    original = json.loads(source.read_text())
    info = inspect_model(path)
    require(info["sha256"] == original["model_sha256"], "Original model source differs")
    archive = source.parent / original["branch_archive"]["file"]
    require(archive.parent == source.parent and digest(archive) == original["branch_archive"]["sha256"],
            "Original branch archive differs")
    branches, seen = {}, set()
    with gzip.open(archive, "rt") as stream:
        for line in stream:
            row = json.loads(line)
            bid = row["branch_id"]
            require(re.fullmatch(r"[0-9a-f]{64}", bid) and bid not in seen, "Duplicate or invalid branch identity")
            require(row["fingerprint"] == original["fingerprint"] and type(row["passed"]) is bool,
                    "Original branch evidence differs")
            seen.add(bid)
            if not row["passed"]:
                branches[bid] = row
    require(len(seen) == original["expected_unique_branches"] == original["evaluated_unique_branches"],
            "Original branch inventory is incomplete")
    config = original["configuration"]
    require(config["dt"] == .01 and config["post_reset_offset"] == 1e-5
            and {k: config["comparison_" + k] for k in ACCEPTANCE} == ACCEPTANCE,
            "Original grid or acceptance thresholds differ")
    ids = ["untreated_baseline", *sorted(branches)]
    require(type(count) is int and count == len(ids) and type(index) is int and 0 <= index < count,
            "Partition count must cover the baseline and every original failed branch")
    grid = sample_times(300., .01, [ResetTrain(t, t+50., {}) for t in (50., 150., 200.)], post_reset_offset=1e-5)
    bid = ids[index]
    times = grid[grid <= 50.] if index == 0 else grid
    trains = [] if index == 0 else branches[bid]["reset_trains"]
    if index:
        require(branches[bid]["sample_count"] == len(grid), "Original branch grid is incomplete")
    core = {"schema": 1, "model_id": mid, "model_sha256": info["sha256"],
            "source_report_sha256": digest(source), "source_archive_sha256": digest(archive),
            "source_fingerprint": original["fingerprint"], "original_failed_branches": ids[1:],
            "requests": deepcopy(REQUESTS), "acceptance": dict(ACCEPTANCE),
            "sample_grid_sha256": hashlib.sha256(grid.tobytes()).hexdigest(), "samples": len(grid),
            "implementation_sha256": {name: digest(ROOT / name) for name in SOURCES}}
    selection = {"index": index, "count": count, "branch_id": bid, "reset_trains": trains,
                 "samples": len(times), "times_sha256": hashlib.sha256(times.tobytes()).hexdigest()}
    return path, info, times, core, selection


def environment():
    import heyoka as hy
    return {"versions": {"heyoka": hy.__version__, **{p: version(p) for p in
                ("numpy", "python-libsbml", "libroadrunner", "pandas")}},
            "python": platform.python_version(), "system": platform.system(), "machine": platform.machine()}


def source_provenance():
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    changed = []
    for name in SOURCES:
        result = subprocess.run(["git", "show", revision + ":python/" + name], cwd=ROOT, capture_output=True)
        if result.returncode or hashlib.sha256(result.stdout).hexdigest() != digest(ROOT / name):
            changed.append(name)
    return {"source_revision": revision, "implementation_files_differing_from_revision": changed}


def verify_report_identity(report, core, selection):
    require(report["core"] == core and report["selection"] == selection,
            "Partition source, numerical request or selection differs")
    runtime = report["environment"]
    require(set(runtime) == {"versions", "python", "system", "machine"}
            and set(runtime["versions"]) == {"heyoka", "numpy", "python-libsbml", "libroadrunner", "pandas"}
            and all(isinstance(v, str) and v for v in (*runtime["versions"].values(),
                                                       runtime["python"], runtime["system"], runtime["machine"])),
            "Incomplete environment provenance")
    require(report["fingerprint"] == signature({"core": core, "environment": runtime, "selection": selection}),
            "Partition fingerprint differs")
    require(report["case_recovery_claimed"] is False, "Partition cannot establish case recovery")


def verify_outcome(evidence, label, info, times, selection):
    require(evidence["completed"] is True and evidence["sample_count"] == len(times)
            and evidence["observables"] == info["observables"] and evidence["model_sha256"] == info["sha256"]
            and evidence["request"] == REQUESTS[label] and evidence["absolute_time_preserved"] is True
            and evidence["times_sha256"] == selection["times_sha256"], "Integration outcome differs")
    if label.startswith("taylor"):
        trains = selection["reset_trains"]
        counts = [len(ResetTrain(**t).indices()) if t["values"] else 0 for t in trains]
        events = sorted({float(v) for t in trains if t["values"] for v in ResetTrain(**t).times()})
        request = REQUESTS[label]
        # MPFR serializes the exact binary value nearest to the decimal request.
        relative_error = abs(Decimal(evidence["tolerance"]) / Decimal(request["tolerance"]) - 1)
        require(evidence["precision_bits"] == request["precision"] and relative_error < Decimal("1e-25")
                and evidence["high_accuracy"] is True
                and evidence["numeric_inputs"] == "binary64 values promoted exactly", "Arithmetic settings differ")
        require(evidence["expected_resets"] == evidence["performed_resets"] == len(events)
                and evidence["expected_train_reset_counts"] == evidence["train_reset_counts"] == counts
                and evidence["expected_segments"] == evidence["completed_segments"] == len(events)+1
                and evidence["last_interval"] == [events[-1] if events else 0., float(times[-1])]
                and type(evidence["integration_steps"]) is int and evidence["integration_steps"] >= 0,
                "Reset or segment coverage is incomplete")
    else:
        require(evidence["event_counters_checked_by_adapter"] is True, "Native reset validation is missing")


def load_trace(directory, report, label, info, times):
    saved = report["traces"][label]
    require(label in REQUESTS and saved["file"] == label + ".npz", "Unexpected trajectory path")
    path = directory / saved["file"]
    require(digest(path) == saved["sha256"], "Trajectory digest differs")
    with np.load(path, allow_pickle=False) as data:
        require(set(data.files) == {"times", "values", "observables"}, "Trajectory member inventory differs")
        names, values = list(data["observables"]), data["values"]
        require(data["times"].dtype == np.float64 and np.array_equal(data["times"], times)
                and names == info["observables"], "Observation inventory differs")
        require(values.dtype == np.float64 and values.shape == (len(times), len(names))
                and np.isfinite(values).all(), "Incomplete trajectory array")
        trace = pd.DataFrame(values.copy(), columns=names)
        trace.insert(0, "time", times)
    verify_outcome(report["integrations"][label], label, info, times, report["selection"])
    return trace


def save_trace(path, times, names, values):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            np.savez_compressed(stream, times=times, values=values, observables=np.asarray(names))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def assess(traces):
    comparisons = {a + "_vs_" + b: comparison(traces[a], traces[b], **ACCEPTANCE)
                   for a, b in PAIRS if a in traces and b in traces}
    converged = comparisons.get("taylor128_vs_taylor192", {}).get("passed", False)
    native = len(comparisons) == 3 and all(c["passed"] for k, c in comparisons.items() if k.endswith("_vs_roadrunner"))
    status = ("incomplete" if len(traces) != 3 else "confirmed" if converged and native else
              "precision_converged_native_mismatch" if converged else "precision_unresolved")
    return {"comparisons": comparisons, "precision_converged": converged, "native_agreement": native,
            "diagnostic_status": status}


def run_partition(model, index, count, output, *, resume=False, max_seconds=14400.):
    """Save each integration independently; never treat a budget stop as failure."""
    require(np.isfinite(max_seconds) and max_seconds > 0, "Positive finite wall budget required")
    path, info, times, core, selection = problem(model, index, count)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".runner.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _run(path, info, times, core, selection, output, resume, max_seconds)


def _run(path, info, times, core, selection, output, resume, max_seconds):
    from .taylor_reference import taylor_trajectory
    started = time.monotonic()
    destination = output / "report.json"
    runtime = environment()
    identity = {"core": core, "environment": runtime, "selection": selection}
    if destination.exists():
        require(resume, "Existing partition requires explicit resume")
        report = json.loads(destination.read_text())
        verify_report_identity(report, core, selection)
        require(report["environment"] == runtime, "Resume environment differs")
    else:
        require(not resume, "Requested partition report is missing")
        require(not any(p.name != ".runner.lock" for p in output.iterdir()), "Fresh partition directory is not empty")
        report = {**identity, "fingerprint": signature(identity), "purpose": __doc__, "started_at": now(),
                  "status": "running", "integrations": {}, "traces": {}, "attempts": [],
                  "integration_history": {}, "case_recovery_claimed": False}
    require(set(report["traces"]) <= set(REQUESTS) and set(report["integrations"]) <= set(REQUESTS),
            "Unexpected integration inventory")
    # Validate all completed integrations before publishing or reusing anything.
    traces = {label: load_trace(output, report, label, info, times) for label in report["traces"]}
    if report["status"] == "completed":
        require(set(traces) == set(REQUESTS) and all(report.get(k) == v for k, v in assess(traces).items()),
                "Completed partition does not reproduce")
        return report
    attempt = {"started_at": now(), **source_provenance(), "platform": platform.platform(),
               "max_seconds": max_seconds, "reused_integrations": list(traces)}
    report["attempts"].append(attempt)
    report.update(status="running", **assess(traces))
    write_json(destination, report)
    for label, request in REQUESTS.items():
        if label in traces:
            continue
        remaining = max_seconds - (time.monotonic() - started)
        if remaining <= 0:
            report["status"] = "budget_exhausted"
            break
        if label in report["integrations"]:
            report["integration_history"].setdefault(label, []).append(deepcopy(report["integrations"][label]))
        evidence = {"completed": False, "request": dict(request), "times_sha256": selection["times_sha256"]}
        report["integrations"][label] = evidence
        write_json(destination, report)
        began = time.monotonic()
        checkpoint = output / (label + "-checkpoint.npz")
        def progress(row):
            if row["completed_segments"] % 100 == 0:
                write_json(destination, report)
                print(selection["branch_id"][:12], label, row["completed_segments"], row["last_interval"], flush=True)
        try:
            if label == "roadrunner":
                trace = protocol_trajectory(path, times, [ResetTrain(**t) for t in selection["reset_trains"]], label, **request)
                names, values = list(trace.columns[1:]), trace.iloc[:, 1:].to_numpy()
                require(np.array_equal(trace.iloc[:, 0].to_numpy(), times), "Native observation times differ")
                evidence.update(completed=True, sample_count=len(times), observables=names,
                                model_sha256=info["sha256"], absolute_time_preserved=True,
                                event_counters_checked_by_adapter=True)
            else:
                names, values = taylor_trajectory(path, times, selection["reset_trains"], **request, evidence=evidence,
                    progress=progress, checkpoint=checkpoint, resume=checkpoint.exists(), max_seconds=remaining)
            require(names == info["observables"] and values.shape == (len(times), len(names))
                    and np.isfinite(values).all(), "Observation inventory differs")
            verify_outcome(evidence, label, info, times, selection)
            trace_path = output / (label + ".npz")
            save_trace(trace_path, times, names, values)
            report["traces"][label] = {"file": trace_path.name, "sha256": digest(trace_path)}
            traces[label] = load_trace(output, report, label, info, times)
        except TaylorCheckpointStop as error:
            evidence.update(completed=False, interruption=str(error), checkpoint_sha256=digest(checkpoint))
            report["status"] = "checkpointed"
        except Exception as error:
            evidence.update(completed=False, error=f"{type(error).__name__}: {error}")
            report["status"] = "integration_failed"
        finally:
            evidence["seconds_this_attempt"] = time.monotonic() - began
            report.update(assess(traces))
            write_json(destination, report)
        if report["status"] != "running":
            break
    if len(traces) == len(REQUESTS):
        report["status"] = "completed"
    attempt.update(finished_at=now(), seconds=time.monotonic()-started, status=report["status"])
    write_json(destination, report)
    print(selection["branch_id"][:12], report["status"], report["diagnostic_status"], flush=True)
    return report
