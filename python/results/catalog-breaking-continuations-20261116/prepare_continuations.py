"""Verify stopped original ZIPs, freshly extract, and prepare the remaining cases."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from grn_memory.breaking_resume import prepare
from scripts.audit_breaking_continuations import digest
from grn_memory.catalog_runner import fingerprint


def verify_stopped_artifact(part, directory, selection, plan):
    """Check original bytes for a terminal but incomplete partition."""
    archive = directory / f'artifact-{part["artifact_id"]}' / "download.zip"
    evidence = archive.parent / "evidence"
    assert Path(part["directory"]).resolve() == evidence.resolve()
    assert "sha256:" + digest(archive) == part["archive_sha256"]
    files, names = {}, set()
    with zipfile.ZipFile(archive) as stream:
        for entry in stream.infolist():
            path = PurePosixPath(entry.filename)
            assert not path.is_absolute() and ".." not in path.parts
            assert entry.filename not in names and not stat.S_ISLNK(entry.external_attr >> 16)
            names.add(entry.filename)
            if entry.is_dir():
                continue
            target = evidence / entry.filename
            assert not target.is_symlink() and target.resolve().is_relative_to(evidence.resolve())
            assert target.is_file() and target.stat().st_size == entry.file_size
            files[entry.filename] = hashlib.sha256(stream.read(entry)).hexdigest()
            assert digest(target) == files[entry.filename]
    actual = list(evidence.rglob("*"))
    assert not any(p.is_symlink() for p in actual)
    assert {str(p.relative_to(evidence)) for p in actual if p.is_file()} == set(files)
    assert digest(evidence / "shard.json") == part["manifest_sha256"]
    manifest = json.loads((evidence / "shard.json").read_text())
    assert all(manifest[k] == plan[k] for k in ("network", "model_id", "shard_count", "expected_model_cases"))
    assert manifest["git_revision"] == selection["producer_revision"]
    assert manifest["shard_index"] == selection["shard_index"]
    assert manifest["selected_coverage_complete"] is False and manifest["status"] == "incomplete"
    assert "finished_at" in manifest and manifest["timed_out"] is True
    return {"verified_files": len(files), "file_inventory_sha256": fingerprint(files),
            "manifest_sha256": digest(evidence / "shard.json")}

SOURCES = {
    5: [
        ("/private/tmp/grn-breaking-collected-network5-targeted-20261114", 43560384864, [13]),
        ("/private/tmp/grn-breaking-collected-continuations-next-20261113", 43485099563, [14]),
        ("/private/tmp/grn-breaking-collected-network5-targeted-20261114", 43560386302, [15]),
    ],
    25: [("/private/tmp/grn-breaking-collected-remaining-20261113", 43374603951, None)],
    29: [("/private/tmp/grn-breaking-collected-continuations-next-20261113", 43485104520, None)],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=int, choices=SOURCES, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for root, run, selected in SOURCES[args.network]:
        collection_dir = Path(root) / str(run) / "attempt-1"
        collection = json.loads((collection_dir / "collection.json").read_text())
        network = collection["networks"][str(args.network)]
        for part in sorted(network["partitions"], key=lambda p: p["shard_index"]):
            index = part["shard_index"]
            if part["selected_coverage_complete"] or (selected is not None and index not in selected):
                continue
            job = next(j for j in network["jobs"] if j["index"] == index)
            assert job["status"] == "completed"
            selection = {"shard_index": index, "run_id": run, "run_attempt": 1,
                         "job_id": job["id"], "producer_revision": collection["producer_revision"]}
            manifest = json.loads((Path(part["directory"]) / "shard.json").read_text())
            assert manifest["timed_out"] is True
            plan = {"network": args.network, "model_id": manifest["model_id"],
                    "shard_count": 16, "expected_model_cases": manifest["expected_model_cases"]}
            verified = verify_stopped_artifact(part, collection_dir, selection, plan)
            archive = collection_dir / f'artifact-{part["artifact_id"]}' / "download.zip"
            destination = args.scratch / f"network-{args.network}" / f"shard-{index}"
            extracted = destination / "source"
            extracted.mkdir(parents=True, exist_ok=False)
            # Every member's name, type and checksum has been checked above.
            with zipfile.ZipFile(archive) as stream:
                stream.extractall(extracted)
            restored = prepare(extracted, destination / "prepared", args.network, index, 16)
            inherited_path = extracted / "resume-source.json"
            inherited = json.loads(inherited_path.read_text()).get("copied_checkpoint_sha256", {}) if inherited_path.exists() else {}
            current = restored["copied_checkpoint_sha256"]
            new = [p for p in current if p not in inherited]
            changed = [p for p in current if p in inherited and current[p] != inherited[p]]
            row = {**selection, "artifact_id": part["artifact_id"], "archive_sha256": digest(archive),
                   "archive_bytes": archive.stat().st_size, "verified_artifact": verified,
                   "finished_at": manifest["finished_at"], "case_keys": manifest["case_keys"],
                   "reported_passed_cases": part["reported_passed_cases"],
                   "new_checkpoints_since_restore": len(new), "changed_inherited_checkpoints": len(changed),
                   "new_branch_checkpoints_since_restore": sum(Path(p).name.startswith("branches-") for p in new),
                   "preparation": {k: restored[k] for k in ("validated_branch_checkpoints", "validated_case_checkpoints",
                       "preserved_case_checkpoints", "copied_checkpoints", "preparation_source_sha256")}}
            rows.append(row)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({"network": args.network, "partitions": rows,
                "original_zip_and_all_extracted_files_verified": True, "fresh_extractions_prepared": True,
                "numerical_integrations_performed": 0, "model_completion_claimed": False}, indent=2) + "\n")
            print(json.dumps({"network": args.network, "index": index, "new_branches": row["new_branch_checkpoints_since_restore"],
                              "changed_inherited": len(changed), **row["preparation"]}), flush=True)


if __name__ == "__main__":
    main()
