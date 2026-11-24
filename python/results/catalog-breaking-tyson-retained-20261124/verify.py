"""Verify retained original Tyson archives; this does not rerun scientific calculations."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

MANIFEST_SHA256 = '046066cf7f79d855e871363aaace12b8bd11ff319c73d9cba10e6f640956cc3f'


def digest(stream):
    return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(directory):
    path = directory/'release-manifest.json'
    assert path.is_file() and not path.is_symlink(), 'Regular manifest required'
    with path.open('rb') as stream:
        assert digest(stream) == MANIFEST_SHA256, 'Fixed manifest differs'
    manifest = json.loads(path.read_text())
    assert manifest['retained_partitions'] == [14, 15] and len(manifest['assets']) == 2
    verified_files = 0
    for row in manifest['assets']:
        archive = directory/row['name']
        assert archive.is_file() and not archive.is_symlink() and archive.stat().st_size == row['bytes']
        with archive.open('rb') as stream:
            assert digest(stream) == row['sha256'], 'Original ZIP differs'
        names, hashes = set(), {}
        with zipfile.ZipFile(archive) as stream:
            for member in stream.infolist():
                name = member.filename.rstrip('/') if member.is_dir() else member.filename
                path = PurePosixPath(name)
                assert name and not path.is_absolute() and '..' not in path.parts and str(path) == name
                assert name not in names and '\\' not in name
                assert not stat.S_ISLNK(member.external_attr >> 16)
                names.add(name)
                if not member.is_dir():
                    with stream.open(member) as data:
                        hashes[member.filename] = digest(data)
        assert hashes == row['files_sha256'], 'Original payload inventory or bytes differ'
        verified_files += len(hashes)
    return {'original_archives_verified': 2, 'retained_partitions': [14, 15],
            'payload_files_verified': verified_files, 'archive_bytes': sum(a['bytes'] for a in manifest['assets']),
            'full_model_completion_claimed': False, 'numerical_integrations_performed': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.assets), indent=2))
