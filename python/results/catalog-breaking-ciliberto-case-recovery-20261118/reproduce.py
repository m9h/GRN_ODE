"""Package preserved Ciliberto evidence, or reproduce its complete case audit offline.

No ODE integrations, artifact selection by outcome, or network requests occur.
The published manifest and pinned repository are the trust anchors for downloads.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def safe_name(name):
    path = PurePosixPath(name)
    require(isinstance(name, str) and name and not path.is_absolute()
            and ".." not in path.parts and str(path) == name and "\\" not in name,
            "Unsafe or noncanonical archive path")
    return path


def checked_file(path, entry):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size == entry["bytes"]
            and digest(path) == entry["sha256"], "Evidence size or checksum differs: " + str(path))


def create_archive(path, entries, sources):
    require(not path.exists(), "Archive already exists")
    with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as archive:
        for entry, source in zip(entries, sources, strict=True):
            safe_name(entry["path"])
            checked_file(source, entry)
            member = tarfile.TarInfo(entry["path"])
            member.size = entry["bytes"]
            member.mode = 0o644
            member.mtime = 0
            with source.open("rb") as stream:
                archive.addfile(member, stream)
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": digest(path), "members": entries}


def extract_archive(path, asset, output):
    checked_file(path, asset)
    expected = {entry["path"]: entry for entry in asset["members"]}
    require(len(expected) == len(asset["members"]), "Duplicate manifest member")
    for name in expected:
        parts = safe_name(name).parts
        require(len(parts) == 2 and parts[0] == asset["role"], "Unexpected evidence prefix")
    with tarfile.open(path, "r:") as archive:
        members = archive.getmembers()
        require(len(members) == len(expected) and {m.name for m in members} == set(expected),
                "Archive inventory differs")
        for member in members:
            entry = expected[member.name]
            require(member.isfile() and member.size == entry["bytes"], "Unexpected archive member type or size")
            target = output / safe_name(member.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("xb") as destination:
                shutil.copyfileobj(source, destination)
            checked_file(target, entry)


def pack(evidence, assets):
    assets.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": 1, "purpose": __doc__, "assets": [],
                "original_report_sha256": read(HERE / "recomputation-plan.json")["original_report_sha256"],
                "preservation_manifest_sha256": digest(HERE / "preservation-manifest.json"),
                "published_audit_sha256": read(HERE / "completed-audit-summary.json")["audit_sha256"],
                "numerical_integrations_performed": 0}
    entries = sorted(read(HERE / "preservation-manifest.json")["files"], key=lambda row: row["path"])
    groups, group, size = [], [], 0
    for entry in entries:
        require(Path(entry["path"]).name == entry["path"], "Preserved filename is not flat")
        if group and size + entry["bytes"] > 1_000_000_000:
            groups.append(group)
            group, size = [], 0
        group.append(entry)
        size += entry["bytes"]
    if group:
        groups.append(group)
    for index, group in enumerate(groups):
        sources = [evidence / "observed-source" / row["path"] for row in group]
        members = [{"path": "preserved/" + row["path"], "bytes": row["bytes"], "sha256": row["sha256"]}
                   for row in group]
        asset = create_archive(assets / f"ciliberto-preserved-{index:02d}.tar", members, sources)
        manifest["assets"].append({"role": "preserved", **asset})
        print(json.dumps({"packed": asset["name"], "bytes": asset["bytes"]}), flush=True)
    plan = read(HERE / "recomputation-plan.json")
    restored_ids = plan["restore_from_release_branch_ids"]
    require(len(restored_ids) == 1, "Expected the single exact restored import")
    bid = restored_ids[0]
    restored = evidence / "restored-import/restored-branch"
    record = read(restored / (bid + ".json"))
    original = read(HERE / "report.json")
    historical = next(row for row in original["branches"] if row["record_id"] == bid)
    require(digest(restored / (bid + ".json")) == historical["sha256"], "Restored record differs")
    for trace in record["traces"].values():
        require(Path(trace["file"]).name == trace["file"], "Unsafe restored array filename")
        require(digest(restored / trace["file"]) == trace["sha256"], "Restored array differs")
    names = [bid + ".json"] + sorted(row["file"] for row in record["traces"].values())
    require(len(names) == 5 and len(set(names)) == 5, "Expected all four restored arrays")
    sources = [restored / name for name in names]
    members = [{"path": "restored/" + name, "bytes": source.stat().st_size, "sha256": digest(source)}
               for name, source in zip(names, sources, strict=True)]
    manifest["assets"].append({"role": "restored", **create_archive(assets / "ciliberto-restored.tar", members, sources)})
    for row in sorted(read(HERE / "completed-collection-status.json")["branches"], key=lambda row: row["index"]):
        name = f"artifact-{row['artifact_id']}.zip"
        asset = {"role": "replacement", "name": name, "bytes": row["archive_bytes"],
                 "sha256": row["archive_sha256"].removeprefix("sha256:"), "artifact_id": row["artifact_id"],
                 "index": row["index"]}
        source = evidence / "downloads" / name
        checked_file(source, asset)
        shutil.copyfile(source, assets / name)
        checked_file(assets / name, asset)
        manifest["assets"].append(asset)
    write(assets / "release-manifest.json", manifest)
    print(json.dumps({"assets": len(manifest["assets"]), "bytes": sum(a["bytes"] for a in manifest["assets"])}), flush=True)


def verify_result(saved_report, fresh_report, saved_audit, fresh_audit):
    # Assembly records its actual finish time. This is the only report field
    # permitted to differ, and consequently the only audit field is its hash.
    old, new = dict(saved_report), dict(fresh_report)
    old.pop("finished_at")
    new.pop("finished_at")
    require(old == new, "Fresh assembled producer report differs beyond assembly timestamp")
    old, new = dict(saved_audit), dict(fresh_audit)
    old.pop("report_sha256")
    new.pop("report_sha256")
    require(old == new, "Fresh complete-case audit differs")


def reproduce(assets, output):
    from scripts.collect_ciliberto_evidence import collect, assemble

    manifest = read(HERE / "release-manifest.json")
    require(manifest["schema_version"] == 1 and manifest["preservation_manifest_sha256"]
            == digest(HERE / "preservation-manifest.json"), "Published preservation manifest differs")
    require(digest(assets / "release-manifest.json") == digest(HERE / "release-manifest.json"),
            "Downloaded manifest differs from pinned repository")
    require(len({a["name"] for a in manifest["assets"]}) == len(manifest["assets"]), "Duplicate asset")
    output.mkdir(parents=True, exist_ok=False)
    archives = output / "archives"
    archives.mkdir()
    for asset in manifest["assets"]:
        require(Path(asset["name"]).name == asset["name"], "Invalid asset filename")
        source = assets / asset["name"]
        checked_file(source, asset)
        if asset["role"] in ("preserved", "restored"):
            extract_archive(source, asset, output)
        else:
            require(asset["role"] == "replacement", "Unexpected asset role")
            shutil.copyfile(source, archives / asset["name"])
        print(json.dumps({"verified_asset": asset["name"]}), flush=True)
    status, experiment = collect(HERE, HERE / "collection-plan.json", HERE / "completed-api", archives, output / "collected")
    require(status["complete_selected_inventory"], "Fixed replacement inventory is incomplete")
    result = assemble(HERE, output / "preserved", output / "restored", output / "assembled", status, experiment)
    fresh_report = read(output / "assembled/report.json")
    fresh_audit = read(output / "assembled/audit.json")
    audit_bytes = gzip.decompress((HERE / "completed-audit.json.gz").read_bytes())
    require(hashlib.sha256(audit_bytes).hexdigest() == manifest["published_audit_sha256"], "Published audit differs")
    verify_result(read(HERE / "completed-producer-report.json"), fresh_report, json.loads(audit_bytes), fresh_audit)
    proof = {"fresh_complete_case_audit_reproduced": True, "verified_release_assets": len(manifest["assets"]),
             "manifest_sha256": digest(HERE / "release-manifest.json"), "reproducer_sha256": digest(Path(__file__)),
             "published_audit_sha256": manifest["published_audit_sha256"], "fresh_audit_sha256": result["audit_sha256"],
             "comparison": "Exact audit JSON equality except report_sha256; assembled reports differ only in finished_at",
             "selected_cases": fresh_audit["selected_cases"], "recovered_selected_cases": fresh_audit["recovered_selected_cases"],
             "baseline_passed": fresh_audit["baseline_passed"], "branches": len(fresh_audit["branches"]),
             "complete_saved_arrays": len(list((output / "assembled").glob("*.npz"))),
             "numerical_integrations_performed": 0, "full_model_coverage_claimed": False}
    write(output / "reproduction-verification.json", proof)
    print(json.dumps(proof), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("pack", "reproduce"))
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.operation == "pack":
        require(args.evidence is not None, "Packing requires --evidence")
        pack(args.evidence, args.assets)
    else:
        require(args.output is not None, "Reproduction requires --output")
        reproduce(args.assets, args.output)


if __name__ == "__main__":
    main()
