"""Verify release packages and repeat the complete-model audits from fresh files."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_breaking_catalog import audit as audit_local
from scripts.audit_breaking_continuations import digest
from scripts.audit_breaking_shards import audit as audit_shards


def portable(result):
    result = json.loads(json.dumps(result))
    for part in result.get("partitions", []):
        part.pop("directory", None)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--network", type=int, choices=[2, 15, 32, 35, 0], action="append")
    args = parser.parse_args()
    assets = json.loads((HERE / "release-assets.json").read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for asset in assets:
        network = asset["network"]
        if args.network is not None and network not in args.network:
            continue
        package = args.assets / asset["name"]
        assert digest(package) == asset["sha256"] and package.stat().st_size == asset["bytes"]
        destination = args.output / (f"network-{network}" if network else "local")
        destination.mkdir(exist_ok=False)
        with tarfile.open(package) as stream:
            stream.extractall(destination, filter="data")
        if network:
            saved = json.loads((ROOT / asset["audit_file"]).read_text())
            provenance = json.loads((ROOT / asset["status_file"]).read_text())
            inputs = []
            for part in provenance["verified_artifacts"]:
                index = part["shard_index"]
                archive = destination / f"shard-{index}.zip"
                assert "sha256:" + digest(archive) == part["archive_sha256"]
                target = destination / f"shard-{index}"
                target.mkdir()
                names = set()
                with zipfile.ZipFile(archive) as stream:
                    for entry in stream.infolist():
                        path = PurePosixPath(entry.filename)
                        assert not path.is_absolute() and ".." not in path.parts
                        assert entry.filename not in names and not stat.S_ISLNK(entry.external_attr >> 16)
                        names.add(entry.filename)
                    stream.extractall(target)
                inputs.append(target)
            result = audit_shards(inputs, network)
            assert portable(result) == portable(saved), "Fresh audit differs from published evidence"
            counts = {k: result[k] for k in ("cases", "passed_cases", "complete_case_coverage", "all_numerical_validations_passed")}
        else:
            saved = json.loads((ROOT / asset["audit_file"]).read_text())
            result = audit_local(destination, saved["source_revision"], saved["selected_networks"])
            assert result == saved, "Fresh local audit differs from published evidence"
            counts = result["totals"]
        row = {"network": network, "asset_sha256": asset["sha256"], "fresh_audit_reproduced": True, **counts}
        results.append(row)
        (args.output / f"verification-{network}.json").write_text(json.dumps(row, indent=2) + "\n")
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
