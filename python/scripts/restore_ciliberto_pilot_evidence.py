"""Restore one missing imported branch exactly from its published arrays."""

import argparse
import hashlib
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import require
from grn_memory.catalog_memory import write_json
from grn_memory.scipy_breaking_recovery import digest
from scripts.recompute_ciliberto_evidence import load_inputs, read
from scripts import diagnose_scipy_breaking_controls as producer


def restore(args):
    plan, report, inventory, model_path, info, grid = load_inputs(args.inputs, args.plan_sha256)
    require(len(plan["restore_from_release_branch_ids"]) == 1, "Expected one published import")
    bid = plan["restore_from_release_branch_ids"][0]
    pilot = ROOT / "results/catalog-breaking-scipy-ciliberto28-shard0"
    download = read(pilot / "download.json")
    require(digest(args.archive) == download["sha256"], "Published archive checksum differs")
    require(not args.output.exists(), "Restore into a new directory")
    archive_dir = args.output / "published-arrays"
    archive_dir.mkdir(parents=True)
    expected = {member["path"]: member for member in download["members"]}
    selected = []
    with tarfile.open(args.archive, "r:gz") as archive:
        members = archive.getmembers()
        require(len(members) == len(expected) and {m.name for m in members} == set(expected),
                "Published archive member inventory differs")
        for member in members:
            entry = expected[member.name]
            require(member.isfile() and member.size == entry["bytes"], "Archive member type or size differs")
            data = archive.extractfile(member).read()
            require(hashlib.sha256(data).hexdigest() == entry["sha256"], "Archive member checksum differs")
            if Path(member.name).name.startswith(bid + "-"):
                target = archive_dir / Path(member.name).name
                target.write_bytes(data)
                selected.append(target.name)
    require(len(selected) == 4, "All four exact original arrays are required")
    prior_report = read(pilot / "report.json")
    require(digest(pilot / "report.json") == report["reused_report_sha256"], "Imported report differs")
    entry = next(e for e in prior_report["branches"] if e["record_id"] == bid)
    require(digest(pilot / entry["file"]) == entry["sha256"], "Imported branch record differs")
    prior = read(pilot / entry["file"])

    def no_integration(*_args, **_kwargs):
        raise RuntimeError("Exact restoration must not perform numerical integration")

    producer.protocol_trajectory = no_integration
    producer.scipy_protocol_trajectory = no_integration
    restored = args.output / "restored-branch"
    restored.mkdir()
    row = producer.compute_branch(
        bid, inventory["branches"][bid], restored, report, grid, model_path, info,
        imported=(prior, archive_dir, {"report_sha256": report["reused_report_sha256"],
                                      "record_sha256": entry["sha256"]}))
    historical = next(e for e in report["branches"] if e["record_id"] == bid)
    require(row == historical, "Restored branch is not byte-identical to the original record")
    proof = {"record_id": bid, "archive_sha256": download["sha256"],
             "verified_archive_members": len(expected), "restored_arrays": 4,
             "restored_record_sha256": row["sha256"], "matches_original_record": True,
             "numerical_integration_performed": False, "full_case_recovery_claimed": False}
    write_json(args.output / "restoration-proof.json", proof)
    print(proof)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    restore(parser.parse_args())
