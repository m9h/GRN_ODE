"""The event encoding preserves the original drive and baseline trajectories."""

import numpy as np
import pytest

from grn_memory.catalog_validation import ROOT, comparison, native_trajectory
from grn_memory.timed_drives import encode_yoon_drives, yoon_trajectory


@pytest.mark.parametrize("engine", ["roadrunner", "copasi"])
def test_explicit_drive_switches_match_the_piecewise_model(engine):
    path = ROOT/"models/BIOMD0000000664.xml"
    before = path.read_bytes()
    times = np.unique(np.r_[np.linspace(0, 50, 5001), 5-1e-6, 5+1e-6, 10-1e-6, 10+1e-6])
    original = native_trajectory(path, times, engine, rtol=1e-12, atol=1e-14)
    encoded = yoon_trajectory(path, times, [], engine, rtol=1e-12, atol=1e-18)
    assert comparison(original, encoded)["passed"]
    np.testing.assert_array_equal(encoded.g1, ((times >= 5) & (times < 10)).astype(float))
    np.testing.assert_array_equal(encoded.g2, (times < 5).astype(float))
    assert path.read_bytes() == before


def test_encoding_rejects_other_models():
    with pytest.raises(ValueError, match="verified BioModel 664"):
        encode_yoon_drives(ROOT/"models/BIOMD0000000038.xml")
