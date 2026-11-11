"""Compare individually scheduled resets with the compact counter encoding.

Diagnostic only: every reset keeps its original time and assignment. The
original model and production adapters are unchanged. Completed mismatches
remain mismatches under the existing full-trajectory comparison.
"""

import argparse
import gzip
import hashlib
from importlib.metadata import version
import json
import logging
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import libsbml

from grn_memory.catalog_validation import native_trajectory, comparison, PACKAGES
from grn_memory.native_protocols import ResetTrain, encode_protocol, sample_times, protocol_trajectory


def explicit_encoding(path, trains):
    doc = libsbml.readSBMLFromString(encode_protocol(path, trains))
    model = doc.getModel()
    for i, train in enumerate(trains):
        if not train.values or not len(train.indices()):
            continue
        template = model.removeEvent(f"grn_protocol_{i}_reset")
        if template is None:
            raise ValueError("Missing compact reset event")
        for index, when in zip(train.indices(), train.times()):
            event = template.clone()
            event.setId(f"grn_protocol_{i}_reset_{index}")
            event.getTrigger().setMath(libsbml.parseL3Formula(f"time >= {when:.17g}"))
            if model.addEvent(event) != libsbml.LIBSBML_OPERATION_SUCCESS:
                raise ValueError("Could not add an explicit reset event")
    result = libsbml.writeSBMLToString(doc)
    checked = libsbml.readSBMLFromString(result)
    if checked.getNumErrors(libsbml.LIBSBML_SEV_ERROR):
        raise ValueError(checked.getErrorLog().toString())
    return result


def diagnose(model_id, branch_id, output):
    path = ROOT/"models"/(model_id+".xml")
    source = ROOT/"results/catalog-paired"/(model_id+".json")
    model = json.loads(source.read_text())
    archive = source.parent/model["branch_archive"]["file"]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == model["branch_archive"]["sha256"]
    with gzip.open(archive, "rt") as stream:
        branch = next(b for line in stream if (b := json.loads(line))["branch_id"] == branch_id)
    trains = [ResetTrain(**t) for t in branch["reset_trains"]]
    grid = sample_times(300., .01, [ResetTrain(t, t+50., {}) for t in (50., 150., 200.)],
                        post_reset_offset=1e-5)
    settings = model["configuration"]["integration_settings"]
    encoded = explicit_encoding(path, trains)
    reference = protocol_trajectory(path, grid, trains, "roadrunner", **settings["roadrunner"])
    columns = list(reference.columns)
    result = {"purpose": __doc__, "model_id": model_id, "branch_id": branch_id,
        "source_fingerprint": model["fingerprint"], "source_report_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "original_model_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "explicit_encoding_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        "reset_counts": [len(t.indices()) for t in trains], "reset_trains": branch["reset_trains"],
        "versions": {p: version(p) for p in PACKAGES}, "runs": []}
    with tempfile.TemporaryDirectory(prefix="grn-explicit-") as temp:
        modified = Path(temp)/"protocol.xml"
        modified.write_text(encoded, encoding="utf-8")
        requests = [(e, settings[e]) for e in ("roadrunner", "copasi")]
        for engine, request in requests:
            started = time.monotonic()
            try:
                trace = native_trajectory(modified, grid, engine, **request)
                for i, train in enumerate(trains):
                    assert trace[f"grn_protocol_{i}_count"].iloc[-1] == train.indices().stop
                check = comparison(reference, trace.loc[:, columns])
                row = {"engine": engine, "settings": request, "comparison_to_compact_roadrunner": check}
            except Exception as exc:
                row = {"engine": engine, "settings": request, "error": f"{type(exc).__name__}: {exc}"}
            row["seconds"] = time.monotonic()-started
            result["runs"].append(row)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
            print(engine, row.get("error", row.get("comparison_to_compact_roadrunner")), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=int, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.getLogger("basico.task_timecourse").setLevel(logging.CRITICAL)
    diagnose(f"BIOMD{args.model:010d}", args.branch, args.output)
