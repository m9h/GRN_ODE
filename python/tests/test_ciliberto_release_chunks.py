"""Storage transport failures and equivalence to the existing full-scope audit."""

from copy import deepcopy
import hashlib
from pathlib import Path
import zipfile

import pytest

from scripts import archive_release_chunks as chunks
from scripts import audit_ciliberto_full_cases as full
from test_ciliberto_full_case_audit import stage_fixture, first_plan
from test_ciliberto_later_controls import context, synthetic
from test_ciliberto_later_collection import branch


class FakeGitHub:
    def __init__(self):
        self.release = {'id': 100, 'tag_name': 'archive-test', 'draft': False}
        self.files = {}
        self.metadata = {}
        self.uploads = 0

    def json(self, endpoint):
        assert endpoint == f'repos/{chunks.REPOSITORY}/releases/tags/archive-test'
        return self.release

    def assets(self, release_id):
        assert release_id == 100
        return deepcopy(list(self.metadata.values()))

    def upload(self, tag, path):
        assert tag == 'archive-test'
        assert path.name not in {a['name'] for a in self.metadata.values()}
        asset_id = len(self.files) + 1
        data = path.read_bytes()
        self.files[asset_id] = data
        self.metadata[asset_id] = {'id': asset_id, 'name': path.name, 'size': len(data),
            'state': 'uploaded', 'digest': 'sha256:' + hashlib.sha256(data).hexdigest()}
        self.uploads += 1

    def download(self, endpoint, path):
        assert endpoint.startswith(f'repos/{chunks.REPOSITORY}/releases/assets/')
        with path.open('xb') as stream:
            stream.write(self.files[int(endpoint.rsplit('/', 1)[1])])


@pytest.mark.parametrize('kind', ['actions/artifacts/123/zip', 'releases/assets/123'])
def test_binary_endpoint_accept_contracts_differ(kind, tmp_path, monkeypatch):
    def run(command, *, stdout, check):
        assert command[-1] == f'repos/{chunks.REPOSITORY}/{kind}' and check
        if kind.startswith('actions/'):
            assert '-H' not in command  # Real Actions endpoint rejects octet-stream with HTTP 415.
        else:
            assert command[3:5] == ['-H', 'Accept: application/octet-stream']
        stdout.write(b'original binary payload')
    monkeypatch.setattr(chunks.subprocess, 'run', run)
    output = tmp_path / 'download'
    chunks.GitHub().download(f'repos/{chunks.REPOSITORY}/{kind}', output)
    assert output.read_bytes() == b'original binary payload'


@pytest.fixture
def archive(tmp_path):
    path = tmp_path / 'original.zip'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as stream:
        stream.writestr('evidence.txt', b'original evidence\n' * 100)
    artifact = {'id': 77, 'name': 'original-artifact', 'size_in_bytes': path.stat().st_size,
                'digest': 'sha256:' + chunks.digest(path),
                'workflow_run': {'id': 123, 'head_sha': 'f' * 40}}
    return path, artifact


def published(archive, tmp_path):
    path, artifact = archive
    api = FakeGitHub()
    receipt = chunks.publish(path, artifact, 'archive-test', tmp_path / 'publication',
                             api=api, chunk_bytes=40)
    return api, receipt


def test_round_trip_restores_exact_original_without_overwriting_assets(archive, tmp_path):
    api, receipt = published(archive, tmp_path)
    count = api.uploads
    repeated = chunks.publish(*archive, 'archive-test', tmp_path / 'retry', api=api, chunk_bytes=40)
    assert receipt == repeated and api.uploads == count
    target = tmp_path / 'fresh'
    target.mkdir()
    restored = chunks.reconstruct(archive[1], receipt, target, api=api)
    assert restored.read_bytes() == archive[0].read_bytes()
    assert not list(target.glob('*.part-*'))
    assert not list((tmp_path / 'publication').glob('*.part-*'))


@pytest.mark.parametrize('fault', ['original_digest', 'original_size', 'release_draft', 'existing_asset'])
def test_publication_cannot_promote_changed_original_or_overwrite(archive, tmp_path, fault):
    path, artifact = archive
    api = FakeGitHub()
    if fault == 'original_digest':
        artifact['digest'] = 'sha256:' + '0' * 64
    elif fault == 'original_size':
        artifact['size_in_bytes'] += 1
    elif fault == 'release_draft':
        api.release['draft'] = True
    else:
        bad = tmp_path / chunks.chunk_name(artifact['id'], 0)
        bad.write_bytes(b'other evidence')
        api.upload('archive-test', bad)
    before = api.uploads
    with pytest.raises(ValueError):
        chunks.publish(path, artifact, 'archive-test', tmp_path / 'publication', api=api, chunk_bytes=40)
    assert api.uploads == before and path.exists()
    assert not any(a['name'].endswith('manifest.json') for a in api.metadata.values())


@pytest.mark.parametrize('fault', ['chunk_bytes', 'chunk_digest', 'missing_chunk', 'manifest_bytes',
                                  'manifest_digest', 'wrong_artifact', 'budget'])
def test_reconstruction_rejects_corruption_and_missing_evidence(archive, tmp_path, fault):
    api, receipt = published(archive, tmp_path)
    artifact = deepcopy(archive[1])
    options = {}
    if fault == 'chunk_bytes':
        api.files[1] = b'wrong'
    elif fault == 'chunk_digest':
        api.metadata[1]['digest'] = 'sha256:' + '0' * 64
    elif fault == 'missing_chunk':
        del api.metadata[1]
    elif fault == 'manifest_bytes':
        api.files[receipt['manifest_asset_id']] = b'{}'
    elif fault == 'manifest_digest':
        receipt['manifest_sha256'] = '0' * 64
    elif fault == 'wrong_artifact':
        artifact['workflow_run']['head_sha'] = 'a' * 40
    else:
        options['max_bytes'] = 1
    target = tmp_path / 'fresh'
    target.mkdir()
    with pytest.raises(ValueError):
        chunks.reconstruct(artifact, receipt, target, api=api, **options)
    assert archive[0].exists()


@pytest.mark.parametrize('fault', ['order', 'missing', 'duplicate', 'filename', 'size', 'scope'])
def test_manifest_cannot_reorder_shrink_or_substitute_chunks(archive, tmp_path, fault):
    api, receipt = published(archive, tmp_path)
    manifest = chunks.read(tmp_path / 'publication/artifact-77.manifest.json')
    if fault == 'order':
        manifest['chunks'].reverse()
    elif fault == 'missing':
        manifest['chunks'].pop()
    elif fault == 'duplicate':
        manifest['chunks'][1] = manifest['chunks'][0]
    elif fault == 'filename':
        manifest['chunks'][0]['name'] = '../outside'
    elif fault == 'size':
        manifest['chunks'][0]['size_in_bytes'] += 1
    else:
        manifest['artifact']['size_in_bytes'] += 1
    with pytest.raises(ValueError):
        chunks.validate_manifest(manifest, archive[1], receipt)


@pytest.mark.parametrize('error_in_consumer', [False, True])
def test_provider_removes_only_temporary_cache_even_when_audit_fails(archive, tmp_path, error_in_consumer):
    api, receipt = published(archive, tmp_path)
    index = tmp_path / 'index.json'
    chunks.write_new(index, {'controls': {'77': receipt}})
    provider = chunks.ReleaseArchiveProvider(index, tmp_path / 'scratch', api=api, max_bytes=1024**3)
    try:
        with provider('controls', {}, {}, archive[1]) as (path, evidence, proof):
            assert path.read_bytes() == archive[0].read_bytes()
            assert (evidence / 'evidence.txt').read_bytes() == b'original evidence\n' * 100
            assert proof['fresh_download_verified'] and proof['expanded_bytes'] == 1800
            if error_in_consumer:
                raise RuntimeError('simulated audit failure')
    except RuntimeError:
        assert error_in_consumer
    assert not list((tmp_path / 'scratch').iterdir())
    assert archive[0].exists() and api.files and index.exists()


def test_provider_rejects_changed_index(archive, tmp_path):
    api, receipt = published(archive, tmp_path)
    index = tmp_path / 'index.json'
    chunks.write_new(index, {'controls': {'77': receipt}})
    provider = chunks.ReleaseArchiveProvider(index, tmp_path / 'scratch', api=api)
    index.write_text('{}')
    with pytest.raises(ValueError, match='index changed'):
        with provider('controls', {}, {}, archive[1]):
            pytest.fail('changed index was accepted')


def test_streamed_stage_matches_cached_numerical_audit_and_preserves_full_scope(branch, context, first_plan, tmp_path):
    paths, validation, output, store, directory = stage_fixture(branch, context, tmp_path)
    original = full.verify_stage('controls', paths, context, first_plan, validation, output, store)
    artifact = full.read(paths['snapshots'] / 'artifacts.json')['artifacts'][0]
    api = FakeGitHub()
    receipt = chunks.publish(directory / 'download.zip', artifact, 'archive-test',
                             tmp_path / 'publication', api=api, chunk_bytes=256 * 1024)
    index = tmp_path / 'index.json'
    chunks.write_new(index, {'controls': {str(artifact['id']): receipt}})
    provider = chunks.ReleaseArchiveProvider(index, tmp_path / 'scratch', api=api, max_bytes=1024**3)
    streamed_output = tmp_path / 'streamed'
    (streamed_output / 'branches').mkdir(parents=True)
    streamed_store = full.BranchStore(streamed_output / 'branches', context[1])
    paths['cache'] = tmp_path / 'cache-does-not-exist'
    result = full.verify_stage('controls', paths, context, first_plan, validation, streamed_output,
                               streamed_store, archive_provider=provider)
    assert not result['verification_errors'] and len(result['pending_partitions']) == 255
    assert result['pending_partitions'] == original['pending_partitions']
    assert len(streamed_store) == len(store) == 7334
    bid = branch[1]['record_id']
    drop_path = lambda row: {k: v for k, v in row.items() if k != 'evidence_directory'}
    assert drop_path(streamed_store[bid]) == drop_path(store[bid])
    assert {k: v for k, v in result['partitions'][0].items() if k != 'archive_preservation'} == original['partitions'][0]
    assert result['partitions'][0]['archive_preservation']['archive_sha256'] == artifact['digest']
    assert not list((tmp_path / 'scratch').iterdir())
