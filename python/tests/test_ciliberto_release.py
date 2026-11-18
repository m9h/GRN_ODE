"""Reject corrupt or incomplete release transport and changed scientific results."""

import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile

import pytest

PATH = Path(__file__).resolve().parents[1] / "results/catalog-breaking-ciliberto-case-recovery-20261118/reproduce.py"
spec = importlib.util.spec_from_file_location("ciliberto_release", PATH)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def archive(tmp_path, names=("preserved/array.npz",), symlink=False):
    path = tmp_path / "input.tar"
    payload = b"saved evidence"
    members = []
    with tarfile.open(path, "w") as tar:
        for name in names:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            if symlink:
                info.type = tarfile.SYMTYPE
                info.linkname = "../../outside"
                info.size = 0
            tar.addfile(info, io.BytesIO(payload))
            members.append({"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    asset = {"role": "preserved", "members": members, "bytes": path.stat().st_size, "sha256": release.digest(path)}
    return path, asset


def test_valid_transport_preserves_bytes(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"all saved observations")
    row = {"path": "preserved/array.npz", "bytes": source.stat().st_size, "sha256": release.digest(source)}
    packed = tmp_path / "packed.tar"
    asset = {"role": "preserved", **release.create_archive(packed, [row], [source])}
    release.extract_archive(packed, asset, tmp_path / "out")
    assert (tmp_path / "out/preserved/array.npz").read_bytes() == source.read_bytes()


@pytest.mark.parametrize("name", ["../outside", "/absolute", "preserved/../outside", "restored/array.npz"])
def test_archive_cannot_escape_expected_evidence_prefix(tmp_path, name):
    path, asset = archive(tmp_path, names=(name,))
    with pytest.raises(ValueError):
        release.extract_archive(path, asset, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_symlink_archive_rejected(tmp_path):
    path, asset = archive(tmp_path, symlink=True)
    with pytest.raises(ValueError, match="member type"):
        release.extract_archive(path, asset, tmp_path / "out")


def test_missing_member_rejected(tmp_path):
    path, asset = archive(tmp_path)
    asset["members"].append({**asset["members"][0], "path": "preserved/missing.npz"})
    with pytest.raises(ValueError, match="inventory differs"):
        release.extract_archive(path, asset, tmp_path / "out")


def test_checksum_tampering_rejected(tmp_path):
    path, asset = archive(tmp_path)
    content = bytearray(path.read_bytes())
    content[512] ^= 1
    path.write_bytes(content)
    with pytest.raises(ValueError, match="checksum differs"):
        release.extract_archive(path, asset, tmp_path / "out")


def test_changed_payload_rejected_even_with_updated_archive_hash(tmp_path):
    path, asset = archive(tmp_path)
    content = bytearray(path.read_bytes())
    content[512] ^= 1
    path.write_bytes(content)
    asset["sha256"] = release.digest(path)
    with pytest.raises(ValueError, match="checksum differs"):
        release.extract_archive(path, asset, tmp_path / "out")


def test_scientific_difference_cannot_hide_behind_new_assembly_time():
    report = {"finished_at": "original", "branches": [{"sha256": "same"}]}
    fresh = {**report, "finished_at": "fresh"}
    audit = {"report_sha256": "old", "recovered_selected_cases": 2}
    release.verify_result(report, fresh, audit, {**audit, "report_sha256": "new"})
    with pytest.raises(ValueError, match="case audit differs"):
        release.verify_result(report, fresh, audit, {**audit, "report_sha256": "new", "recovered_selected_cases": 1})
    with pytest.raises(ValueError, match="producer report differs"):
        release.verify_result(report, {**fresh, "branches": [{"sha256": "changed"}]}, audit, audit)
