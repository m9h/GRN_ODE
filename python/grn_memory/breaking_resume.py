"""Validate and copy existing checkpoints into a finer whole-case partition."""

from contextlib import ExitStack
import fcntl
import gzip
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import shutil
import tempfile

from .breaking_audit import audit_branch, audit_case, require
from .breaking_shards import select_cases
from .catalog_breaking import candidate_plans
from .catalog_memory import write_json
from .catalog_runner import fingerprint
from .catalog_validation import ROOT, inspect_model


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_source_hash(name):
    return digest(ROOT/"grn_memory"/name)


def prepare(source, output, network, index, count):
    source, output = Path(source).resolve(), Path(output).resolve()
    require(not output.exists(), "Destination must not already exist")
    require(not output.is_relative_to(source), "Destination must be outside the source artifact")
    with ExitStack() as stack:
        lock_path = source/".shard.lock"
        if lock_path.exists():
            lock = stack.enter_context(lock_path.open("rb"))
            try:
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError("Source partition is still in use") from error
        manifest_path = source/"shard.json"
        manifest_sha = digest(manifest_path)
        manifest = json.loads(manifest_path.read_text())
        require(manifest["status"] in ("selected_cases_passed", "selected_cases_failed", "incomplete", "empty_shard")
                and "finished_at" in manifest, "Source partition must have stopped")
        old_count, old_index = manifest["shard_count"], manifest["shard_index"]
        require(old_count > 0 and count >= old_count and count % old_count == 0 and 0 <= index < count,
                "New partition count must be a positive multiple of the previous count")
        require(old_index == index*old_count//count, "Wrong parent partition for the new selection")
        entry = next(e for e in json.loads((ROOT/"models/catalog.json").read_text())["models"] if e["network"] == network)
        mid = entry["biomodel_id"]
        require(manifest["network"] == network and manifest["model_id"] == mid, "Source model differs")
        reference_path = ROOT/"results/catalog-repeated"/(mid+".json")
        reference = json.loads(reference_path.read_text())
        require(reference["status"] == "passed", "Validated repeated-screen calibration is required")
        plans = candidate_plans(reference)
        fields = ("network", "model_id", "shard_index", "shard_count", "candidate_plan_sha256",
                  "reference_file_sha256", "case_keys", "expected_model_cases", "selected_case_count")
        require(fingerprint({k: manifest[k] for k in fields}) == manifest["selection_sha256"], "Source selection hash differs")
        require(manifest["candidate_plan_sha256"] == fingerprint(plans)
                and manifest["reference_file_sha256"] == digest(reference_path), "Source candidate plan or calibration differs")
        selected = select_cases(plans, index, count)
        require(manifest["case_keys"] == select_cases(plans, old_index, old_count)
                and manifest["expected_model_cases"] == len(plans)
                and manifest["selected_case_count"] == len(manifest["case_keys"]), "Source partition inventory differs")
        require(set(selected) <= set(manifest["case_keys"]), "New cases fall outside the parent selection")
        require(manifest["executed_control"] == (not plans and old_index == 0), "Source control selection differs")
        checkpoint_files, report_sha, signature = {}, None, None
        report_path = source/(mid+".json")
        records = {"branches": {}, "cases": {}}
        if report_path.exists():
            report_sha = digest(report_path)
            require(report_sha == manifest["model_report_sha256"], "Source report digest differs")
            report = json.loads(report_path.read_text())
            fields = ("configuration", "model_sha256", "reference_fingerprint", "reference_file_sha256",
                      "implementation_sha256", "versions")
            signature = fingerprint({k: report[k] for k in fields})
            require(signature == report["fingerprint"] == manifest["model_fingerprint"], "Source model fingerprint differs")
            info = inspect_model(ROOT/"models"/(mid+".xml"))
            require(report["model_sha256"] == reference["model_sha256"] == info["sha256"]
                    and report["reference_fingerprint"] == reference["fingerprint"]
                    and report["reference_file_sha256"] == digest(reference_path), "Model or calibration provenance differs")
            for name, sha in report["implementation_sha256"].items():
                require(runtime_source_hash(name) == sha, "Current worker source differs: "+name)
            require(all(version(package) == value for package, value in report["versions"].items()),
                    "Current worker package versions differ")
            cache = source/".evidence"/mid/signature
            require(cache.is_dir(), "Atomic checkpoint directory is missing")
            for path in sorted(cache.glob("*.json.gz")):
                require(not path.is_symlink() and path.resolve().is_relative_to(cache.resolve()), "Checkpoint path escapes its directory")
                kind, key = path.name.removesuffix(".json.gz").split("-", 1)
                require(kind in records and len(key) == 64 and all(c in "0123456789abcdef" for c in key), "Invalid checkpoint name")
                with gzip.open(path, "rt") as stream:
                    row = json.load(stream)
                require(row["fingerprint"] == signature and row["record_id"] == key, "Checkpoint identity differs")
                records[kind][key] = row
                checkpoint_files[str(path.relative_to(source))] = digest(path)
            for row in records["branches"].values():
                audit_branch(row, report, info["observables"])
            by_id = {fingerprint(plan): plan for plan in plans.values()}
            for key, row in records["cases"].items():
                require(key in by_id, "Checkpoint case is not in the full candidate plan")
                audit_case(row, by_id[key], records["branches"], report, reference)
            # A later run may carry valid unused checkpoints inherited from its
            # parent. They remain reusable; only selected cases are executed.
        else:
            require(manifest["status"] == "empty_shard" and not manifest["case_keys"]
                    and not manifest["executed_control"], "Nonempty source has no model report")
        require(digest(manifest_path) == manifest_sha, "Source manifest changed during validation")
        if report_path.exists():
            require(digest(report_path) == report_sha, "Source report changed during validation")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="grn-resume-", dir=output.parent) as temporary:
            staging = Path(temporary)/"prepared"
            staging.mkdir()
            copied = checkpoint_files if selected or (not plans and index == 0) else {}
            for relative, sha in copied.items():
                dest = staging/relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source/relative, dest)
                require(digest(dest) == sha, "Checkpoint changed while copying")
            result = {"purpose": __doc__, "network": network, "model_id": mid,
                      "shard_index": index, "shard_count": count, "case_keys": selected,
                      "source_shard_index": old_index, "source_shard_count": old_count,
                      "source_git_revision": manifest["git_revision"], "source_manifest_sha256": manifest_sha,
                      "source_report_sha256": report_sha, "model_fingerprint": signature,
                      "validated_branch_checkpoints": len(records["branches"]),
                      "validated_case_checkpoints": len(records["cases"]),
                      "copied_checkpoint_sha256": copied, "copied_checkpoints": len(copied),
                      "numerical_integrations_performed": 0, "model_completion_claimed": False,
                      "preparation_source_sha256": digest(Path(__file__))}
            write_json(staging/"resume-source.json", result)
            staging.rename(output)
        return result
