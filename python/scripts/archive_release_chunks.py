"""Preserve exact Actions ZIPs in releases; reconstruct one at a time for audit.

Transport only: no model, integration, or numerical acceptance code lives here.
Existing release assets are never overwritten. A manifest is published only after
every chunk has been downloaded again and the original ZIP checksum reproduced.
"""

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

REPOSITORY = 'm9h/GRN_ODE'
CHUNK_BYTES = 500 * 1024**2
DEFAULT_BUDGET = 16 * 1024**3


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text())


def write_new(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def artifact_identity(artifact):
    require(type(artifact['id']) is int and artifact['id'] > 0
            and type(artifact['size_in_bytes']) is int and artifact['size_in_bytes'] > 0
            and re.fullmatch(r'sha256:[0-9a-f]{64}', artifact['digest']),
            'Original artifact ID, size and SHA-256 are required')
    return {key: artifact[key] for key in ('id', 'name', 'size_in_bytes', 'digest', 'workflow_run')}


def check_file(path, size, sha):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size == size
            and digest(path) == sha, 'Downloaded bytes differ from pinned size or SHA-256')


def chunk_name(artifact_id, index):
    return f'artifact-{artifact_id}.zip.part-{index:04d}'


class GitHub:
    """Use authenticated gh without persisting redirects or bearer tokens."""

    def json(self, endpoint):
        return json.loads(subprocess.check_output(['gh', 'api', endpoint]))

    def download(self, endpoint, path):
        with path.open('xb') as stream:
            subprocess.run(['gh', 'api', '--allow-escape-sequences',
                            '-H', 'Accept: application/octet-stream', endpoint],
                           stdout=stream, check=True)

    def assets(self, release_id):
        pages = json.loads(subprocess.check_output(['gh', 'api', '--paginate', '--slurp',
            f'repos/{REPOSITORY}/releases/{release_id}/assets?per_page=100']))
        assets = [asset for page in pages for asset in page]
        require(len({a['id'] for a in assets}) == len(assets)
                and len({a['name'] for a in assets}) == len(assets), 'Duplicate release assets')
        return assets

    def upload(self, tag, path):
        subprocess.run(['gh', 'release', 'upload', tag, str(path), '--repo', REPOSITORY], check=True)


def check_asset(asset, name, size, sha):
    require(asset['name'] == name and asset['size'] == size and asset['state'] == 'uploaded'
            and asset.get('digest') == 'sha256:' + sha, 'Release asset identity or checksum differs')


def find_or_upload(api, release, path, size, sha):
    matches = [a for a in api.assets(release['id']) if a['name'] == path.name]
    require(len(matches) <= 1, 'Duplicate release asset')
    if not matches:
        api.upload(release['tag_name'], path)
        matches = [a for a in api.assets(release['id']) if a['name'] == path.name]
    require(len(matches) == 1, 'Published asset is not uniquely visible; inspect before retrying')
    check_asset(matches[0], path.name, size, sha)
    return matches[0]


def publish(archive, artifact, tag, scratch, *, api=None, chunk_bytes=CHUNK_BYTES):
    """Upload at most one temporary chunk at a time; leave the original untouched."""
    api = api or GitHub()
    identity = artifact_identity(artifact)
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]+', tag), 'Unsafe release tag')
    require(type(chunk_bytes) is int and 0 < chunk_bytes <= CHUNK_BYTES, 'Invalid chunk size')
    check_file(archive, identity['size_in_bytes'], identity['digest'][7:])
    release = api.json(f'repos/{REPOSITORY}/releases/tags/{tag}')
    require(not release['draft'] and release['tag_name'] == tag, 'Public release must exist first')
    require(not scratch.exists(), 'Use a fresh publication working directory')
    scratch.mkdir(parents=True)
    chunks, recovered_sha = [], hashlib.sha256()
    with archive.open('rb') as source:
        index = 0
        while data := source.read(chunk_bytes):
            path = scratch / chunk_name(identity['id'], index)
            with path.open('xb') as stream:
                stream.write(data)
            size, sha = len(data), hashlib.sha256(data).hexdigest()
            del data
            asset = find_or_upload(api, release, path, size, sha)
            path.unlink()  # Only this generated chunk; the original ZIP remains.
            api.download(f'repos/{REPOSITORY}/releases/assets/{asset["id"]}', path)
            check_file(path, size, sha)
            with path.open('rb') as stream:
                while block := stream.read(8 * 1024**2):
                    recovered_sha.update(block)
            chunks.append({'index': index, 'name': path.name, 'asset_id': asset['id'],
                           'size_in_bytes': size, 'sha256': sha})
            path.unlink()
            index += 1
    require(recovered_sha.hexdigest() == identity['digest'][7:],
            'Freshly downloaded chunks do not reproduce the original ZIP')
    manifest = {'schema_version': 1, 'repository': REPOSITORY, 'release_id': release['id'],
                'release_tag': tag, 'artifact': identity, 'chunk_bytes': chunk_bytes, 'chunks': chunks}
    path = scratch / f'artifact-{identity["id"]}.manifest.json'
    write_new(path, manifest)
    asset = find_or_upload(api, release, path, path.stat().st_size, digest(path))
    remote_manifest = scratch / 'manifest.fresh-download.json'
    api.download(f'repos/{REPOSITORY}/releases/assets/{asset["id"]}', remote_manifest)
    check_file(remote_manifest, path.stat().st_size, digest(path))
    receipt = {'release_id': release['id'], 'release_tag': tag, 'manifest_asset_id': asset['id'],
               'manifest_sha256': digest(path), 'manifest_bytes': path.stat().st_size,
               'artifact_id': identity['id'], 'archive_sha256': identity['digest'],
               'archive_bytes': identity['size_in_bytes'], 'fresh_download_verified': True}
    write_new(scratch / 'receipt.json', receipt)
    return receipt


def validate_manifest(manifest, artifact, receipt):
    identity = artifact_identity(artifact)
    require(manifest['schema_version'] == 1 and manifest['repository'] == REPOSITORY
            and manifest['artifact'] == identity
            and manifest['release_id'] == receipt['release_id']
            and manifest['release_tag'] == receipt['release_tag']
            and receipt['artifact_id'] == identity['id']
            and receipt['archive_sha256'] == identity['digest']
            and receipt['archive_bytes'] == identity['size_in_bytes']
            and receipt['fresh_download_verified'] is True, 'Pinned archive manifest identity differs')
    size = manifest['chunk_bytes']
    require(type(size) is int and 0 < size <= CHUNK_BYTES, 'Invalid manifest chunk size')
    expected_count = (identity['size_in_bytes'] + size - 1) // size
    chunks = manifest['chunks']
    require(len(chunks) == expected_count and len({c['asset_id'] for c in chunks}) == len(chunks),
            'Missing or duplicate archive chunks')
    for index, chunk in enumerate(chunks):
        require(chunk['index'] == index and chunk['name'] == chunk_name(identity['id'], index)
                and chunk['size_in_bytes'] == min(size, identity['size_in_bytes'] - index * size)
                and type(chunk['asset_id']) is int and chunk['asset_id'] > 0
                and re.fullmatch(r'[0-9a-f]{64}', chunk['sha256']), 'Chunk order, size or identity differs')


def reconstruct(artifact, receipt, directory, *, api=None, max_bytes=DEFAULT_BUDGET):
    """Fresh downloads, bounded temporary storage, exact original ZIP checksum."""
    api = api or GitHub()
    identity = artifact_identity(artifact)
    require(identity['size_in_bytes'] + CHUNK_BYTES <= max_bytes,
            'Archive exceeds the configured storage budget')
    require(type(receipt['manifest_bytes']) is int and 0 < receipt['manifest_bytes'] < 1024**2,
            'Manifest size is invalid')
    manifest_path = directory / 'manifest.json'
    api.download(f'repos/{REPOSITORY}/releases/assets/{receipt["manifest_asset_id"]}', manifest_path)
    check_file(manifest_path, receipt['manifest_bytes'], receipt['manifest_sha256'])
    manifest = read(manifest_path)
    validate_manifest(manifest, artifact, receipt)
    assets = {a['id']: a for a in api.assets(receipt['release_id'])}
    archive = directory / 'download.zip'
    with archive.open('xb') as destination:
        for chunk in manifest['chunks']:
            require(chunk['asset_id'] in assets, 'Pinned archive chunk is missing')
            check_asset(assets[chunk['asset_id']], chunk['name'], chunk['size_in_bytes'], chunk['sha256'])
            path = directory / chunk['name']
            api.download(f'repos/{REPOSITORY}/releases/assets/{chunk["asset_id"]}', path)
            check_file(path, chunk['size_in_bytes'], chunk['sha256'])
            with path.open('rb') as source:
                shutil.copyfileobj(source, destination)
            path.unlink()
    check_file(archive, identity['size_in_bytes'], identity['digest'][7:])
    return archive


class ReleaseArchiveProvider:
    """One original ZIP plus its extraction; never delete caller-owned evidence."""

    def __init__(self, index_path, scratch, *, api=None, max_bytes=DEFAULT_BUDGET):
        self.index_path, self.index_sha = index_path, digest(index_path)
        self.index, self.scratch = read(index_path), scratch
        self.api, self.max_bytes = api or GitHub(), max_bytes
        require(set(self.index) <= {'diagnostics', 'controls'}, 'Unknown evidence stage')
        require(type(max_bytes) is int and max_bytes > 0, 'Invalid storage budget')
        scratch.mkdir(parents=True, exist_ok=True)
        require(not scratch.is_symlink(), 'Scratch directory must not be a symlink')

    @contextmanager
    def __call__(self, stage, row, run, artifact):
        require(digest(self.index_path) == self.index_sha, 'Archive index changed during audit')
        receipt = self.index[stage][str(artifact['id'])]
        # Only generated scratch files are removed, including on a failed audit.
        # The verified remote archive and all prior local evidence remain intact.
        with tempfile.TemporaryDirectory(prefix='archive-audit-', dir=self.scratch) as temporary:
            directory = Path(temporary)
            require(shutil.disk_usage(directory).free >= self.max_bytes,
                    'Insufficient free space for configured archive budget')
            archive = reconstruct(artifact, receipt, directory, api=self.api, max_bytes=self.max_bytes)
            with zipfile.ZipFile(archive) as stream:
                expanded = sum(info.file_size for info in stream.infolist())
            require(archive.stat().st_size + expanded + (directory / 'manifest.json').stat().st_size
                    <= self.max_bytes, 'Expanded archive exceeds the configured storage budget')
            from scripts.collect_ciliberto_full_diagnostics import verify_zip
            evidence = directory / 'evidence'
            verify_zip(archive, evidence, extract=True)
            proof = {'kind': 'release_chunks', 'index_sha256': self.index_sha, **receipt,
                     'expanded_bytes': expanded, 'storage_budget_bytes': self.max_bytes}
            yield archive, evidence, proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--artifact-metadata', type=Path, required=True)
    parser.add_argument('--release-tag', required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(publish(args.archive, read(args.artifact_metadata), args.release_tag, args.scratch)))
