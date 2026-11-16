"""Atomic numeric checkpoints for the restricted Taylor protocol adapter.

The checkpoint contains decimal MPFR state, JSON metadata and binary64 saved
observations. It contains no pickled objects or compiled executable code.
Resuming requires the same model, complete protocol, source and environment.
"""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

import numpy as np


class TaylorCheckpointStop(RuntimeError):
    """A requested cooperative stop after saving exact integration state."""


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


@contextmanager
def checkpoint_lock(path, resume):
    if path is None:
        if resume:
            raise ValueError("Resume requires a checkpoint path")
        yield
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists() and not resume:
            raise ValueError("Existing Taylor checkpoint requires explicit resume")
        if resume and not path.exists():
            raise ValueError("Requested Taylor checkpoint is missing")
        yield


def save(path, identity, state, observations, evidence, real):
    """Round-trip every internal state value before atomically publishing it."""
    encoded = [str(value) for value in state]
    if any(not np.isfinite(value) or real(text) != value for text, value in zip(encoded, state)):
        raise ValueError("Decimal checkpoint does not preserve exact internal state")
    observations = np.asarray(observations, dtype=np.float64)
    if not np.isfinite(observations).all():
        raise ValueError("Checkpoint observations must be complete and finite")
    metadata = {"schema": 2, "identity": identity, "identity_sha256": signature(identity),
                "state": encoded, "evidence": evidence,
                "observations_sha256": hashlib.sha256(observations.tobytes()).hexdigest()}
    metadata["payload_sha256"] = signature(metadata)
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            np.savez_compressed(stream, metadata=np.asarray(json.dumps(metadata, sort_keys=True, allow_nan=False)),
                                observations=observations)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load(path, identity, times, edges, events, base_evidence, real):
    """Validate identity, observations and all protocol counters before reuse."""
    with np.load(path, allow_pickle=False) as data:
        if set(data.files) != {"metadata", "observations"}:
            raise ValueError("Taylor checkpoint member inventory differs")
        metadata = json.loads(str(data["metadata"]))
        observations = data["observations"].copy()
    recorded_signature = metadata.pop("payload_sha256")
    if (signature(metadata) != recorded_signature or metadata["schema"] not in (1, 2)
            or metadata["identity"] != identity or metadata["identity_sha256"] != signature(identity)):
        raise ValueError("Taylor checkpoint identity or metadata checksum differs")
    evidence = metadata["evidence"]
    k = evidence["completed_segments"]
    active = evidence.get("active_segment")
    if (type(k) is not int or not 0 <= k < len(edges)
            or k == 0 and active is None or metadata["schema"] == 1 and active is not None):
        raise ValueError("Invalid checkpoint segment count")
    final = k == len(edges) - 1
    end = float(edges[k])
    if active is None:
        last = int(np.searchsorted(times, end, side="right" if final else "left"))
        expected_resets = [when for when in events if when < end]
    else:
        if (final or set(active) != {"index", "interval", "dtime", "saved_samples"}
                or type(active["index"]) is not int or active["index"] != k
                or active["interval"] != [end, float(edges[k+1])]
                or not isinstance(active["dtime"], list) or len(active["dtime"]) != 2
                or not all(isinstance(v, str) for v in active["dtime"])):
            raise ValueError("Invalid checkpoint active segment")
        hi, lo = map(real, active["dtime"])
        if (not np.isfinite([hi, lo]).all() or hi + lo != hi
                or not (hi > real(end) or hi == real(end) and lo > 0)
                or not (hi < real(float(edges[k+1])) or hi == real(float(edges[k+1])) and lo < 0)):
            raise ValueError("Invalid checkpoint compensated clock")
        # Compare the normalized two-component clock without discarding its
        # low part or rounding it through binary64 near an observation time.
        last = int(np.searchsorted(times, float(hi), side="right"))
        def reached(t):
            target = real(float(t))
            return target < hi or target == hi and lo >= 0
        while last and not reached(times[last-1]):
            last -= 1
        while last < len(times) and reached(times[last]):
            last += 1
        if type(active["saved_samples"]) is not int or active["saved_samples"] != last:
            raise ValueError("Checkpoint active observation prefix differs")
        expected_resets = [when for when in events if when <= end]
    expected_counts = [sum(index in events[when]["trains"] for when in expected_resets)
                       for index in range(len(base_evidence["expected_train_reset_counts"]))]
    counters = {"performed_resets", "train_reset_counts", "completed_segments", "integration_steps", "completed"}
    if any(evidence.get(key) != value for key, value in base_evidence.items() if key not in counters):
        raise ValueError("Checkpoint model, precision or observation evidence differs")
    if (evidence["performed_resets"] != len(expected_resets) or evidence["train_reset_counts"] != expected_counts
            or evidence.get("last_interval") != ([float(edges[k-1]), end] if k else None)
            or evidence["completed"] is not final
            or type(evidence["integration_steps"]) is not int or evidence["integration_steps"] < 0):
        raise ValueError("Checkpoint reset, segment or completion evidence differs")
    if (observations.dtype != np.float64 or observations.shape != (last, len(identity["observables"]))
            or not np.isfinite(observations).all()
            or hashlib.sha256(observations.tobytes()).hexdigest() != metadata["observations_sha256"]):
        raise ValueError("Checkpoint observation prefix differs")
    state = [real(value) for value in metadata["state"]]
    if len(state) != len(identity["observables"]) or not all(np.isfinite(value) for value in state):
        raise ValueError("Checkpoint internal state is incomplete or nonfinite")
    return state, observations, evidence
