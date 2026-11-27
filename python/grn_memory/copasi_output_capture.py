"""Observe COPASI output without changing time-course arguments or return values.

The observer functions are preserved verbatim from the earlier Vilar capture
at revision 30eb1e29442748c4fcf443777841537b71e5e8d9.
"""
import gzip
import hashlib
import logging
from pathlib import Path
import shutil
import COPASI
import numpy as np

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def copasi_messages():
    return COPASI.CCopasiMessage.getAllMessageText()

def observe_time_course(original, destination, monitor, *args, **kwargs):
    """Observe one unchanged call; never pad, trim, interpolate or retry output."""
    # Basico consumes solver exceptions before returning the partial array.
    # Its logger therefore retains information absent from CCopasiMessage.
    logger = logging.getLogger("basico.task_timecourse")
    old_handlers, old_level, old_propagate = logger.handlers, logger.level, logger.propagate
    log_path = destination.with_suffix(".log")
    handler = logging.FileHandler(log_path, mode="x", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.handlers, logger.propagate = [handler], False
    logger.setLevel(logging.WARNING)
    try:
        output = original(*args, **kwargs)
    finally:
        logger.handlers, logger.propagate = old_handlers, old_propagate
        logger.setLevel(old_level)
        handler.close()
        compressed = log_path.with_suffix(".log.gz")
        with log_path.open("rb") as source, compressed.open("wb") as target:
            with gzip.GzipFile(fileobj=target, mode="wb", filename="", mtime=0) as stream:
                shutil.copyfileobj(source, stream)
        text = log_path.read_text(encoding="utf-8")
        monitor["timecourse_log"] = {"file": compressed.name, "sha256": digest(compressed),
                                     "uncompressed_bytes": log_path.stat().st_size, "tail": text[-1500:]}
        log_path.unlink()
        monitor["copasi_messages"] = copasi_messages()
    monitor["output_type"] = type(output).__name__
    monitor["settings"] = {key: kwargs.get(key) for key in
                           ("r_tol", "a_tol", "max_steps", "automatic", "output_event", "method")}
    monitor["requested_samples"] = len(kwargs["values"])
    monitor["requested_times_sha256"] = hashlib.sha256(np.asarray(kwargs["values"], dtype=np.float64).tobytes()).hexdigest()
    if hasattr(output, "to_numpy"):
        values = output.to_numpy()
        names = [str(name) for name in output.columns]
        monitor["shape"] = list(values.shape)
        monitor["columns"] = names
        if len(values):
            monitor["last_row"] = {name: float(value) if np.isfinite(value) else str(value)
                                   for name, value in zip(names, values[-1])}
        np.savez_compressed(destination, values=values, columns=np.asarray(names))
        monitor["raw_output"] = {"file": destination.name, "sha256": digest(destination)}
    return output
