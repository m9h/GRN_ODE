"""Explicit migration of the pinned legacy unfinished Taylor128 checkpoint.

Only scheduling/checkpoint representation changes. Preserve the original report,
original checkpoint and converted starting checkpoint, and verify their lineage
on every subsequent resume and audit. No integration is performed here.
"""

from copy import deepcopy
import json
from pathlib import Path
import shutil

import numpy as np

from . import taylor_checkpoints as checkpoints
from .catalog_memory import write_json
from .taylor_partitions import digest, environment, now, problem, require, verify_report_identity

LEGACY_REVISION = "50740779287606d05eae34b2197fc9cb27394fe6"
LEGACY_SOURCES = {
    "grn_memory/taylor_partitions.py": "015f50c51115918dddd84447977940b22c39bbe450bc1fe3dbac20cf7501bbe9",
    "grn_memory/taylor_reference.py": "dc862c86914791dd58952273c798b58fd6a65ac967d33f0678c1204e59584b18",
    "grn_memory/taylor_checkpoints.py": "3e0e49af62c37f67fbb573e3bf7e8cbc67bef1c152e146266f6de958623fd85f",
    "grn_memory/native_protocols.py": "bc7d49a05a87cb2855131985ca88f47e1d32ca29d31fd5c0f567714699f172c9",
    "grn_memory/catalog_validation.py": "d5fa5611d1c3c8ab0ed5fb4aca567c6504dae33e7e79800d640008746b16669f",
    "grn_memory/catalog_memory.py": "abc6b6a497bf5686ec930918ebda320f784329952f45282a0f042f726fb1e1ba",
    "scripts/run_taylor_checkpoint_partition.py": "b58193838e5595231b85738a7c26cc7dc623c002b105d791afaff20ca74a8f66",
}
FILES = ("legacy-report.json", "legacy-taylor128-checkpoint.npz", "segment-start-checkpoint.npz")


def legacy_core(core):
    original = deepcopy(core)
    original["implementation_sha256"] = dict(LEGACY_SOURCES)
    return original


def legacy_identity(identity):
    original = deepcopy(identity)
    original.pop("checkpoint_steps")
    original["sources"] = {"adapter": LEGACY_SOURCES["grn_memory/taylor_reference.py"],
                           "checkpoints": LEGACY_SOURCES["grn_memory/taylor_checkpoints.py"]}
    return original


def snapshot(path):
    with np.load(path, allow_pickle=False) as data:
        require(set(data.files) == {"metadata", "observations"}, "Migration checkpoint members differ")
        metadata = json.loads(str(data["metadata"]))
        observations = data["observations"].copy()
    checksum = metadata.pop("payload_sha256")
    require(checkpoints.signature(metadata) == checksum, "Migration checkpoint checksum differs")
    require(metadata["identity_sha256"] == checkpoints.signature(metadata["identity"]),
            "Migration checkpoint identity checksum differs")
    import hashlib
    require(observations.dtype == np.float64 and observations.ndim == 2 and np.isfinite(observations).all()
            and hashlib.sha256(observations.tobytes()).hexdigest() == metadata["observations_sha256"],
            "Migration observations differ")
    return metadata, observations


def verify_migration(directory, report):
    """Verify retained bytes and unchanged prefix without requiring Heyoka."""
    directory = Path(directory)
    binding = report.get("checkpoint_migration")
    manifest = directory / "checkpoint-migration.json"
    if binding is None:
        require(not manifest.exists() and not any((directory / name).exists() for name in FILES),
                "Unbound checkpoint migration evidence")
        return
    require(binding == {"file": manifest.name, "sha256": digest(manifest)}, "Migration manifest binding differs")
    record = json.loads(manifest.read_text())
    require(record["schema"] == 1 and record["legacy_source_revision"] == LEGACY_REVISION
            and record["integrations_performed"] == 0 and record["case_recovery_claimed"] is False
            and record["new_core_sha256"] == checkpoints.signature(report["core"])
            and record["files"] == {name: digest(directory / name) for name in FILES},
            "Migration lineage or retained files differ")
    original = json.loads((directory / "legacy-report.json").read_text())
    verify_report_identity(original, legacy_core(report["core"]), report["selection"])
    require(original["environment"] == report["environment"] and not original["traces"],
            "Migration original environment or completed trace inventory differs")
    before, observations = snapshot(directory / "legacy-taylor128-checkpoint.npz")
    after, converted = snapshot(directory / "segment-start-checkpoint.npz")
    runtime, selection = report["environment"], report["selection"]
    versions = runtime["versions"]
    expected = {"model_sha256": report["core"]["model_sha256"], "precision_bits": 128,
                "times_sha256": selection["times_sha256"], "samples": selection["samples"],
                "trains": selection["reset_trains"], "high_accuracy": True, "compact_mode": True,
                "numeric_inputs": "binary64 values promoted exactly",
                "environment": {"heyoka": versions["heyoka"], "numpy": versions["numpy"],
                    "libsbml": versions["python-libsbml"], "python": runtime["python"],
                    "system": runtime["system"], "machine": runtime["machine"]}}
    require(all(after["identity"].get(key) == value for key, value in expected.items()),
            "Migration checkpoint differs from the selected model or protocol")
    require(before["schema"] == 1 and after["schema"] == 2
            and before["identity"] == legacy_identity(after["identity"])
            and after["identity"]["checkpoint_steps"] == 1_000_000
            and after["identity"]["sources"] == {
                "adapter": report["core"]["implementation_sha256"]["grn_memory/taylor_reference.py"],
                "checkpoints": report["core"]["implementation_sha256"]["grn_memory/taylor_checkpoints.py"]}
            and before["state"] == after["state"] and before["evidence"] == after["evidence"]
            and before["evidence"]["completed"] is False and "active_segment" not in before["evidence"]
            and np.array_equal(observations, converted), "Migration changed state, clock, protocol or observations")
    require(record["completed_segments"] == before["evidence"]["completed_segments"]
            and record["saved_samples"] == len(observations), "Migration prefix counters differ")
    current = directory / "taylor128.npz"
    if current.exists():
        with np.load(current, allow_pickle=False) as data:
            prefix = data["values"][:len(observations)]
    else:
        _, prefix = snapshot(directory / "taylor128-checkpoint.npz")
        prefix = prefix[:len(observations)]
    require(np.array_equal(prefix, observations), "Resumed trajectory changed the preserved legacy prefix")


def migrate(directory, model, index, count):
    """Convert only a verified, unfinished legacy first-precision checkpoint.

The caller operates on a fresh staging directory, retaining its original ZIP.
Other legacy source versions and completed solver arrays require separate review.
    """
    from .taylor_partition_resume import checkpoint_context, validate_evidence
    directory = Path(directory)
    _, info, times, core, selection = problem(model, index, count)
    report_path = directory / "report.json"
    report = json.loads(report_path.read_text())
    verify_report_identity(report, legacy_core(core), selection)
    require(report["environment"] == environment(), "Migration environment differs")
    require(report["status"] in ("running", "checkpointed", "budget_exhausted", "integration_failed")
            and not report["traces"] and set(report["integrations"]) == {"taylor128"},
            "Migration requires only an unfinished Taylor128 integration")
    require(not any((directory / name).exists() for name in (*FILES, "checkpoint-migration.json"))
            and not report.get("checkpoint_migration"), "Checkpoint has already been migrated")
    identity, edges, events, expected, real = checkpoint_context(info, times, selection, "taylor128")
    checkpoint = directory / "taylor128-checkpoint.npz"
    metadata, _ = snapshot(checkpoint)
    require(metadata["schema"] == 1, "Only the pinned schema-1 checkpoint can be migrated")
    state, observations, evidence = checkpoints.load(checkpoint, legacy_identity(identity), times,
                                                    edges, events, expected, real)
    require(not evidence["completed"] and "active_segment" not in evidence,
            "Migration requires an unfinished checkpoint at a protocol boundary")
    require(not (directory / "taylor192-checkpoint.npz").exists()
            and not any((directory / (label + ".npz")).exists() for label in ("taylor128", "taylor192", "roadrunner")),
            "Unexpected solver arrays in legacy migration")
    shutil.copyfile(report_path, directory / "legacy-report.json")
    shutil.copyfile(checkpoint, directory / "legacy-taylor128-checkpoint.npz")
    checkpoints.save(checkpoint, identity, state, observations, evidence, real)
    shutil.copyfile(checkpoint, directory / "segment-start-checkpoint.npz")
    record = {"schema": 1, "migrated_at": now(), "legacy_source_revision": LEGACY_REVISION,
              "new_core_sha256": checkpoints.signature(core), "integrations_performed": 0,
              "case_recovery_claimed": False, "completed_segments": evidence["completed_segments"],
              "saved_samples": len(observations), "files": {name: digest(directory / name) for name in FILES},
              "reason": "Save exact state inside long segments without repeating completed legacy work"}
    manifest = directory / "checkpoint-migration.json"
    write_json(manifest, record)
    report["core"] = core
    report["fingerprint"] = checkpoints.signature({key: report[key] for key in ("core", "environment", "selection")})
    report["checkpoint_migration"] = {"file": manifest.name, "sha256": digest(manifest)}
    write_json(report_path, report)
    validate_evidence(directory, model, index, count)
    return record
