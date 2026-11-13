"""Interrupted precision calculations must preserve the full protocol exactly."""

import fcntl
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

hy = pytest.importorskip("heyoka")

from grn_memory import taylor_checkpoints as checkpoints
from grn_memory import taylor_reference as adapter
from test_taylor_reference import decay


@pytest.fixture
def protocol(tmp_path):
    path = decay(tmp_path, .25)
    times = np.array([0., .39, .41, .79, .81, 1.19, 1.21, 1.6, 2.])
    trains = [dict(start=.4, stop=1.6, values={"A": 4.}, interval=.4),
              dict(start=.4, stop=1.2, values={"B": 4.}, interval=.4, include_start=True, include_stop=True)]
    return path, times, trains, tmp_path / "state.npz"


def saved(path):
    with np.load(path, allow_pickle=False) as data:
        return json.loads(str(data["metadata"])), data["observations"].copy()


def alter(path, change):
    metadata, observations = saved(path)
    observations = change(metadata, observations)
    metadata["observations_sha256"] = hashlib.sha256(observations.tobytes()).hexdigest()
    del metadata["payload_sha256"]
    metadata["payload_sha256"] = checkpoints.signature(metadata)
    np.savez_compressed(path, metadata=np.asarray(json.dumps(metadata)), observations=observations)


@pytest.mark.parametrize("bits,tolerance", [(128, "1e-30"), (192, "1e-45")])
def test_repeated_resume_preserves_every_observation_and_reset(protocol, bits, tolerance):
    path, times, trains, checkpoint = protocol
    kwargs = dict(precision=bits, tolerance=tolerance)
    reference = {}
    names, uninterrupted = adapter.taylor_trajectory(path, times, trains, evidence=reference, **kwargs)
    for index in range(3):
        with pytest.raises(checkpoints.TaylorCheckpointStop):
            adapter.taylor_trajectory(path, times, trains, checkpoint=checkpoint, resume=index > 0,
                                     stop_after_segments=1, **kwargs)
        metadata, observations = saved(checkpoint)
        assert metadata["evidence"]["completed_segments"] == index + 1
        assert metadata["evidence"]["performed_resets"] == index
        assert not metadata["evidence"]["completed"]
        # The checkpoint's internal state must retain digits beyond binary64.
        assert any(hy.real(value, bits) != hy.real(float(value), bits) for value in metadata["state"])
        np.testing.assert_array_equal(observations, uninterrupted[:len(observations)])
    evidence = {}
    resumed_names, resumed = adapter.taylor_trajectory(path, times, trains, checkpoint=checkpoint,
                                                       resume=True, evidence=evidence, **kwargs)
    assert names == resumed_names
    np.testing.assert_array_equal(resumed, uninterrupted)
    assert {k: evidence[k] for k in reference} == reference
    assert evidence["resumed_from_checkpoint_segments"] == 3
    assert saved(checkpoint)[0]["evidence"]["completed"]


def test_completed_checkpoint_needs_no_further_integration(protocol, monkeypatch):
    path, times, trains, checkpoint = protocol
    expected = adapter.taylor_trajectory(path, times, trains, checkpoint=checkpoint)[1]
    def forbidden(*args, **kwargs):
        raise AssertionError("A completed checkpoint should not integrate again")
    monkeypatch.setattr(hy, "taylor_adaptive", forbidden)
    actual = adapter.taylor_trajectory(path, times, trains, checkpoint=checkpoint, resume=True)[1]
    np.testing.assert_array_equal(actual, expected)


@pytest.fixture
def interrupted(protocol):
    path, times, trains, checkpoint = protocol
    with pytest.raises(checkpoints.TaylorCheckpointStop):
        adapter.taylor_trajectory(path, times, trains, checkpoint=checkpoint, stop_after_segments=1)
    return protocol


@pytest.mark.parametrize("change", ["model", "grid", "train", "precision", "tolerance", "environment"])
def test_resume_rejects_changed_problem_or_environment(interrupted, change, monkeypatch):
    path, times, trains, checkpoint = interrupted
    kwargs = {}
    if change == "model":
        path.write_text(path.read_text().replace('stoichiometry="0.25"', 'stoichiometry="0.5"'))
    elif change == "grid":
        times = times.copy(); times[1] = .38
    elif change == "train":
        trains[0]["values"]["A"] = 5.
    elif change == "precision":
        kwargs["precision"] = 192
    elif change == "tolerance":
        kwargs["tolerance"] = "1e-31"
    else:
        monkeypatch.setattr(hy, "__version__", "changed")
    with pytest.raises(ValueError, match="identity"):
        adapter.taylor_trajectory(path, times, trains, checkpoint=checkpoint, resume=True, **kwargs)


@pytest.mark.parametrize("change", ["reset", "counts", "interval", "completed", "segment", "truncate", "nonfinite"])
def test_semantic_corruption_is_rejected_with_recomputed_checksums(interrupted, change):
    path, times, trains, checkpoint = interrupted
    def modify(metadata, observations):
        row = metadata["evidence"]
        if change == "reset": row["performed_resets"] = 1
        elif change == "counts": row["train_reset_counts"] = [1, 0]
        elif change == "interval": row["last_interval"] = [0., .39]
        elif change == "completed": row["completed"] = True
        elif change == "segment": row["completed_segments"] = 0
        elif change == "truncate": return observations[:-1]
        else: observations[0, 0] = np.nan
        return observations
    alter(checkpoint, modify)
    with pytest.raises(ValueError, match="checkpoint|Checkpoint"):
        adapter.taylor_trajectory(path, times, trains, checkpoint=checkpoint, resume=True)


def test_failed_atomic_save_preserves_last_complete_checkpoint(interrupted, monkeypatch):
    path, times, trains, checkpoint = interrupted
    previous = checkpoint.read_bytes()
    def failed_replace(*args):
        raise OSError("simulated interrupted publication")
    monkeypatch.setattr(checkpoints.os, "replace", failed_replace)
    with pytest.raises(OSError, match="interrupted publication"):
        adapter.taylor_trajectory(path, times, trains, checkpoint=checkpoint, resume=True, stop_after_segments=1)
    assert checkpoint.read_bytes() == previous
    assert not list(checkpoint.parent.glob(checkpoint.name + ".*.tmp"))


def test_existing_checkpoint_cannot_be_overwritten_implicitly(interrupted):
    path, times, trains, checkpoint = interrupted
    previous = checkpoint.read_bytes()
    with pytest.raises(ValueError, match="explicit resume"):
        adapter.taylor_trajectory(path, times, trains, checkpoint=checkpoint)
    assert checkpoint.read_bytes() == previous


def test_concurrent_writer_is_rejected(interrupted):
    path, times, trains, checkpoint = interrupted
    with checkpoint.with_name(checkpoint.name + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            adapter.taylor_trajectory(path, times, trains, checkpoint=checkpoint, resume=True)


def test_wall_budget_saves_a_completed_segment(protocol, monkeypatch):
    path, times, trains, checkpoint = protocol
    clock = iter([0., 2.])
    monkeypatch.setattr(adapter.time, "monotonic", lambda: next(clock))
    with pytest.raises(checkpoints.TaylorCheckpointStop):
        adapter.taylor_trajectory(path, times, trains, checkpoint=checkpoint, max_seconds=1.)
    assert saved(checkpoint)[0]["evidence"]["completed_segments"] == 1


@pytest.mark.parametrize("model", [35, 39])
@pytest.mark.parametrize("bits,tolerance", [(128, "1e-30"), (192, "1e-45")])
def test_short_vilar_and_marhl_probe_matches_uninterrupted(tmp_path, model, bits, tolerance):
    """Short implementation probes, not validation of the full memory protocol."""
    path = Path(__file__).resolve().parents[1] / "models" / f"BIOMD{model:010d}.xml"
    _, _, _, writable = adapter._model(path, bits)
    times = np.array([0., .049, .051, .099, .101, .149, .151, .2])
    trains = [dict(start=0., stop=.2, interval=.05, values={sorted(writable)[0]: 1.})]
    options = dict(precision=bits, tolerance=tolerance)
    reference = tmp_path / "uninterrupted.npz"
    expected = adapter.taylor_trajectory(path, times, trains, checkpoint=reference, **options)[1]
    checkpoint = tmp_path / "model.npz"
    with pytest.raises(checkpoints.TaylorCheckpointStop):
        adapter.taylor_trajectory(path, times, trains, checkpoint=checkpoint, stop_after_segments=2, **options)
    actual = adapter.taylor_trajectory(path, times, trains, checkpoint=checkpoint, resume=True, **options)[1]
    np.testing.assert_array_equal(actual, expected)
    original, resumed = saved(reference)[0], saved(checkpoint)[0]
    assert original["state"] == resumed["state"]
    assert original["evidence"]["integration_steps"] == resumed["evidence"]["integration_steps"]
