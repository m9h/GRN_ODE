"""Verify all sixteen original Cellière artifacts and reproduce the model audit.

This checks saved comparison and window evidence; it does not integrate ODEs
or reconstruct raw trajectories that the original producer did not retain.
"""

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_breaking_continuations import digest, validate_plan, verify_artifact
from scripts.audit_breaking_shards import audit


def portable(result):
    result = json.loads(json.dumps(result))
    for partition in result["partitions"]:
        partition.pop("directory", None)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    assets = json.loads((HERE / "release-assets.json").read_text())
    plan = json.loads((HERE / "selection-plan.json").read_text())
    status = json.loads((HERE / "status.json").read_text())
    saved = json.loads((HERE / "audit.json").read_text())
    assert digest(HERE / "audit.json") == status["model_audit_sha256"]
    selections = validate_plan(plan)
    assert [a["shard_index"] for a in assets] == list(range(16))
    assert [p["shard_index"] for p in status["verified_artifacts"]] == list(range(16))
    assert digest(ROOT / "scripts/audit_breaking_shards.py") == saved["audit_script_sha256"]
    assert digest(ROOT / "grn_memory/breaking_audit.py") == saved["audit_module_sha256"]
    args.output.mkdir(parents=True, exist_ok=False)
    directories, verification = [], []
    for asset, selection, provenance in zip(assets, selections, status["verified_artifacts"], strict=True):
        assert asset["shard_index"] == selection["shard_index"] == provenance["shard_index"]
        assert asset["artifact_id"] == provenance["artifact_id"]
        assert asset["sha256"] == provenance["archive_sha256"].removeprefix("sha256:")
        assert asset["bytes"] == provenance["archive_bytes"]
        assert Path(asset["name"]).name == asset["name"]
        source = args.assets / asset["name"]
        assert digest(source) == asset["sha256"] and source.stat().st_size == asset["bytes"]
        artifact = args.output / f"artifact-{asset['artifact_id']}"
        directory = artifact / "evidence"
        directory.mkdir(parents=True)
        archive = artifact / "download.zip"
        try:
            os.link(source, archive)
        except OSError:
            shutil.copyfile(source, archive)
        names = set()
        with zipfile.ZipFile(archive) as stream:
            for member in stream.infolist():
                name = PurePosixPath(member.filename)
                assert not name.is_absolute() and ".." not in name.parts
                assert member.filename not in names and not stat.S_ISLNK(member.external_attr >> 16)
                names.add(member.filename)
            stream.extractall(directory)
        partition = {**provenance, "directory": str(directory)}
        checked_directory, checked = verify_artifact(partition, args.output, selection, plan)
        assert checked == provenance, "Fresh artifact verification differs from original"
        directories.append(checked_directory)
        verification.append(checked)
        print(json.dumps({"verified_shard": asset["shard_index"], "artifact_id": asset["artifact_id"]}), flush=True)
    result = audit(directories, 29)
    assert portable(result) == portable(saved), "Fresh model audit differs from published evidence"
    (args.output / "audit.json").write_text(json.dumps(result, indent=2) + "\n")
    evidence = {"network": 29, "fresh_audit_reproduced": True,
                "comparison": "Exact JSON equality after removing only partition extraction-directory paths",
                "original_audit_sha256": digest(HERE / "audit.json"),
                "reproducer_sha256": digest(Path(__file__)),
                "verified_artifacts": verification,
                "numerical_integrations_performed": 0,
                **{key: result[key] for key in ("cases", "passed_cases", "conditional_trials", "response_trials",
                                               "complete_case_coverage", "all_numerical_validations_passed")}}
    (args.output / "reproduction-verification.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({k: v for k, v in evidence.items() if k != "verified_artifacts"}), flush=True)


if __name__ == "__main__":
    main()
