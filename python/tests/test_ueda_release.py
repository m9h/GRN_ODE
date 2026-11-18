"""Reject corrupt or incomplete release transport and changed scientific results."""

import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile

import pytest

PATH = Path(__file__).resolve().parents[1] / "results/catalog-breaking-ueda-continuation-20261118/reproduce.py"
spec = importlib.util.spec_from_file_location("ueda_release", PATH)
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



def test_preparation_requires_exact_outputs_and_pinned_hashes(tmp_path, monkeypatch):
    pinned, fresh = tmp_path/'pinned', tmp_path/'fresh'
    pinned.mkdir(); fresh.mkdir()
    monkeypatch.setattr(release, 'HERE', pinned)
    for name in release.PREPARATION_OUTPUTS:
        (pinned/name).write_text('{"result": 1}\n')
        (fresh/name).write_bytes((pinned/name).read_bytes())
    manifest = {'preparation_outputs_sha256': {n: release.digest(pinned/n) for n in release.PREPARATION_OUTPUTS}}
    release.verify_result(manifest, fresh)
    changed = release.PREPARATION_OUTPUTS[0]
    (fresh/changed).write_text('{"result": 2}\n')
    with pytest.raises(ValueError, match='does not reproduce exactly'):
        release.verify_result(manifest, fresh)
    (pinned/changed).write_bytes((fresh/changed).read_bytes())
    with pytest.raises(ValueError, match='Pinned preparation evidence differs'):
        release.verify_result(manifest, fresh)


def test_missing_preparation_output_rejected(tmp_path):
    with pytest.raises(ValueError, match='output inventory differs'):
        release.verify_result({'preparation_outputs_sha256': {}}, tmp_path)
