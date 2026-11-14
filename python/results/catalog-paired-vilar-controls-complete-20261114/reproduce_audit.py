"""Verify and re-audit the unchanged workflow artifacts in this release."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def portable(report):
    result = copy.deepcopy(report)
    for evidence in result["branch_evidence"].values():
        evidence.pop("directory")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Repository python directory")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New extraction and audit directory")
    args = parser.parse_args()
    sys.path.insert(0, str(args.source.resolve()))
    from grn_memory.taylor_case_controls import audit_cases
    from grn_memory.taylor_partition_resume import extract

    bundle = args.bundle.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    sources = json.loads((bundle / "sources.json").read_text())["sources"]
    directories = []
    for source in sources:
        archive = (bundle / source["release_archive"]).resolve()
        if not archive.is_relative_to(bundle):
            raise ValueError("Archive path leaves bundle")
        if archive.stat().st_size != source["archive_bytes"]:
            raise ValueError(f"Archive size mismatch: {archive.name}")
        if digest(archive.read_bytes()) != source["archive_sha256"].removeprefix("sha256:"):
            raise ValueError(f"Archive hash mismatch: {archive.name}")
        with zipfile.ZipFile(archive) as stream:
            members = {entry.filename: digest(stream.read(entry))
                       for entry in stream.infolist() if not entry.is_dir()}
        if members != source["public_evidence_sha256"]:
            raise ValueError(f"Member hash mismatch: {archive.name}")
        destination = args.output / archive.stem
        extract(archive, destination)
        directories.append(destination / "evidence")

    plan = json.loads((bundle / "plan.json").read_text())
    report = audit_cases(plan, directories, allow_partial=True)
    expected = json.loads((bundle / "partial-case-audit.json").read_text())
    if portable(report) != portable(expected):
        raise ValueError("Recomputed audit differs from saved result")
    (args.output / "recomputed-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"audited_trajectories": len(report["branch_evidence"]),
                      "missing_trajectories": len(report["missing_branch_ids"]),
                      "recovered_cases": report["recovered_cases"],
                      "reproduces_saved_audit": True}))


if __name__ == "__main__":
    main()
