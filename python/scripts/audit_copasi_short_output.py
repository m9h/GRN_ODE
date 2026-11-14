"""Recompute saved-array comparisons and inspect conserved promoter pools.

No numerical integration is performed. Invariants describe the original SBML
between imposed resets; measurements from RoadRunner alone are labelled as
diagnostics and do not establish cross-simulator agreement or case recovery.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import libsbml
import numpy as np
import pandas as pd

from grn_memory.catalog_memory import write_json
from grn_memory.catalog_repeated import pulse_schedule, trains_for
from grn_memory.catalog_validation import comparison, inspect_model
from grn_memory.native_protocols import ResetTrain, sample_times
from scripts.diagnose_breaking_refinement import refinement_requests
from scripts.diagnose_copasi_short_output import ADAPTERS, digest, require


def conserved_pools(path):
    document = libsbml.readSBML(str(path)); model = document.getModel()
    result = {}
    require(not model.isSetConversionFactor(), "Model conversion factor needs separate analysis")
    targets = {r.getVariable() for r in model.getListOfRules()}
    targets.update(a.getVariable() for e in model.getListOfEvents() for a in e.getListOfEventAssignments())
    for pool in (("DA", "DAp"), ("DR", "DRp")):
        require(not targets.intersection(pool), "An original rule or event changes a pool species")
        species = [model.getSpecies(name) for name in pool]
        compartments = {s.getCompartment() for s in species}
        require(len(compartments) == 1 and all(not s.getConstant() and not s.getBoundaryCondition()
                and not s.isSetConversionFactor() for s in species), "Pool interpretation requires ordinary species in one compartment")
        compartment = model.getCompartment(next(iter(compartments)))
        require(compartment.getConstant() and compartment.getId() not in targets, "Pool volume is not constant")
        residuals = {}
        for reaction in model.getListOfReactions():
            refs = list(reaction.getListOfReactants())+list(reaction.getListOfProducts())
            require(all(not ref.isSetStoichiometryMath() for ref in refs), "Dynamic stoichiometry needs separate analysis")
            residuals[reaction.getId()] = (sum(r.getStoichiometry() for r in reaction.getListOfProducts() if r.getSpecies() in pool)
                                          -sum(r.getStoichiometry() for r in reaction.getListOfReactants() if r.getSpecies() in pool))
        require(all(value == 0 for value in residuals.values()), "Pool is not conserved by original reactions")
        result["+".join(pool)] = {"species": list(pool), "reaction_stoichiometric_residuals": residuals,
                                "constant_compartment": compartment.getId(), "compartment_size": compartment.getSize(),
                                "claim": "Sum of concentrations is constant between external resets"}
    return result


def audit(directory):
    directory = Path(directory)
    report = json.loads((directory/"report.json").read_text())
    source = json.loads((directory/"source-evidence.json").read_text())
    require(report["status"] == "completed" and report["expected_records"] == len(report["records"]) == 3,
            "All three selected records must finish")
    require(not report["case_recovery_claimed"] and digest(directory/"source-evidence.json") == report["source_evidence_sha256"],
            "Source identity or recovery claim differs")
    model_path = ROOT/"models/BIOMD0000000035.xml"; info = inspect_model(model_path)
    require(info["sha256"] == report["model_sha256"], "Model differs")
    require(set(report["implementation_sha256"]) == set(ADAPTERS), "Adapter inventory differs")
    recorded_sources = {"scripts/diagnose_copasi_short_output.py": report["script_sha256"],
                        "scripts/diagnose_breaking_refinement.py": report["refinement_policy_sha256"],
                        **{"grn_memory/"+name: sha for name, sha in report["implementation_sha256"].items()}}
    for name, sha in recorded_sources.items():
        content = subprocess.check_output(["git", "show", report["source_revision"]+":python/"+name], cwd=ROOT)
        require(hashlib.sha256(content).hexdigest() == sha, "Producer source differs: "+name)
    require(all(digest(ROOT/"grn_memory"/name) == report["implementation_sha256"][name] for name in ADAPTERS),
            "Audit adapter source differs")
    selected = {s["record"]["record_id"]: s for s in source["selected_records"]}
    require(len(selected) == 3 and {r["record_id"] for r in report["records"]} == set(selected), "Selected inventory differs")
    possible = trains_for(pulse_schedule(), {})+[ResetTrain(t,t+100.,{}) for t in (1010.,1210.,1410.,1610.,1810.,2010.)]
    grid = sample_times(2210., .01, possible, post_reset_offset=1e-5)
    rows = []
    for entry in report["records"]:
        bid = entry["record_id"]; path = directory/entry["file"]
        require(entry["file"] == bid+".json" and digest(path) == entry["sha256"], "Record identity differs")
        record = json.loads(path.read_text()); original = selected[bid]["record"]; spec = original["specification"]
        require(selected[bid]["model_id"] == "BIOMD0000000035" and selected[bid]["model_sha256"] == info["sha256"],
                "Selected original model differs")
        require(record["source_record_id"] == bid and record["specification"] == spec
                and record["original_error"] == original["error"], "Original protocol differs")
        times = grid[grid <= spec["stop"]]
        require(record["samples"] == original["sample_count"] == len(times)
                and record["times_sha256"] == hashlib.sha256(times.tobytes()).hexdigest(), "Full observation grid differs")
        requests = {engine+"_"+label: settings for engine in ("roadrunner", "copasi")
                    for label,settings in refinement_requests(spec["integration_settings"][engine]).items()}
        require(set(record["integrations"]) == set(requests), "Integration request inventory differs")
        traces, native = {}, {}
        for label, request in requests.items():
            integration = record["integrations"][label]
            require(integration["request"] == request and type(integration["completed"]) is bool, "Integration request differs")
            if integration["completed"]:
                saved = record["trajectories"][label]; path = directory/saved["file"]
                require(saved["file"] == bid+"-"+label+".npz" and digest(path) == saved["sha256"], "Trajectory hash differs")
                with np.load(path, allow_pickle=False) as data:
                    require(set(data.files) == {"times", "values", "observables"}
                            and np.array_equal(data["times"], times) and list(data["observables"]) == info["observables"]
                            and data["values"].shape == (len(times),len(info["observables"]))
                            and data["values"].dtype == np.float64 and np.isfinite(data["values"]).all(), "Incomplete trajectory")
                    traces[label] = pd.DataFrame(data["values"].copy(),columns=info["observables"])
                    traces[label].insert(0,"time",times)
            if label.startswith("copasi"):
                settings = integration["settings"]
                require(settings == {"r_tol":request["rtol"],"a_tol":request["atol"],"max_steps":100000,
                                     "automatic":False,"output_event":False,"method":"deterministic"}, "COPASI request was altered")
                require(integration["requested_samples"] == len(times)
                        and integration["requested_times_sha256"] == record["times_sha256"], "COPASI was given a different grid")
                raw = integration["raw_output"]; raw_path = directory/raw["file"]
                require(raw["file"] == bid+"-"+label+"-raw.npz" and digest(raw_path) == raw["sha256"], "Raw output hash differs")
                with np.load(raw_path, allow_pickle=False) as data:
                    values = data["values"]
                    require(list(values.shape) == integration["shape"] and list(data["columns"]) == integration["columns"], "Raw output inventory differs")
                    last_time = float(values[-1,0]); returned_rows = len(values)
                log = integration["timecourse_log"]; log_path = directory/log["file"]
                require(log["file"] == bid+"-"+label+"-raw.log.gz" and digest(log_path) == log["sha256"], "Solver log hash differs")
                with gzip.open(log_path,"rt") as stream: text = stream.read()
                require(len(text.encode()) == log["uncompressed_bytes"] and text[-1500:] == log["tail"], "Solver log summary differs")
                require(integration["completed"] or returned_rows < len(times), "Failed run does not have truncated output")
                native[label] = {"completed":integration["completed"], "returned_rows":returned_rows,
                                 "required_rows":len(times), "last_time":last_time,
                                 "step_limit_exhausted":"MXSTEP" in text and "I1 = '100000'" in text,
                                 "clock_resolution_warning":"T + H = T" in text,
                                 "log_sha256":log["sha256"]}
        pairs = [("roadrunner_"+label,"copasi_"+label) for label in ("original","tight","tighter")]
        pairs += [(engine+"_"+a,engine+"_"+b) for engine in ("roadrunner","copasi") for a,b in (("original","tight"),("tight","tighter"))]
        comparisons = {a+"_vs_"+b: comparison(traces[a],traces[b],rtol=2e-5,atol=1e-7) for a,b in pairs if a in traces and b in traces}
        require(comparisons == record["comparisons"], "Saved comparisons do not reproduce")
        required = [a+"_vs_"+b for a,b in pairs if "original" not in a+"_vs_"+b]
        require(record["refinement_confirmed"] == entry["refinement_confirmed"] == all(comparisons.get(k,{}).get("passed",False) for k in required), "Refinement claim differs")
        diagnostics = []
        if "roadrunner_tighter" in traces:
            trace = traces["roadrunner_tighter"]
            for when in (0.,1000.,float(times[-1])):
                frame = trace.loc[np.isclose(times,when,rtol=0,atol=1e-9)]
                require(len(frame)==1,"Diagnostic clock sample missing")
                point=frame.iloc[0]
                diagnostics.append({"time":when,"DA+DAp":float(point.DA+point.DAp),"DR+DRp":float(point.DR+point.DRp),"A":float(point.A)})
        rows.append({"record_id":bid,"samples":len(times),"copasi":native,"comparisons":comparisons,
                     "refinement_confirmed":record["refinement_confirmed"],"roadrunner_tighter_diagnostics":diagnostics})
    return {"purpose":__doc__,"report_sha256":digest(directory/"report.json"),"model_sha256":info["sha256"],
            "audit_script_sha256":digest(Path(__file__)),"conserved_pools":conserved_pools(model_path),"records":rows,
            "full_arrays_recompared":True,"case_recovery_claimed":False,"model_completion_claimed":False}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(); result=audit(args.input)
    args.output.parent.mkdir(parents=True,exist_ok=True);write_json(args.output,result)
    print(json.dumps({"records":len(result["records"]),"copasi_step_limit_failures":sum(v["step_limit_exhausted"] for r in result["records"] for v in r["copasi"].values()),"full_arrays_recompared":True,"case_recovery_claimed":False}))
