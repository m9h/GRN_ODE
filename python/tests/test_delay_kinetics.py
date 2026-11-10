"""A known piecewise polynomial checks delay history, including boundaries."""

import numpy as np
import pytest

from grn_memory.scheper_delay import method_of_steps


def exact_delayed_growth(times):
    # y'(t)=y(t-1), y(t<=0)=1. Valid on 0 <= t <= 3.
    return 1+times+np.maximum(times-1, 0)**2/2+np.maximum(times-2, 0)**3/6


def test_method_of_steps_against_delayed_polynomial():
    times = np.linspace(0, 3, 31)
    values = method_of_steps(lambda t, state, past: past, times, [1], 1)
    np.testing.assert_allclose(values[:, 0], exact_delayed_growth(times), rtol=1e-10, atol=1e-11)


def test_jitcdde_against_delayed_polynomial():
    import importlib.util
    import subprocess
    import sys
    if importlib.util.find_spec("jitcdde") is None:
        pytest.skip("Optional delay engine not installed")
    # SymEngine/JiTCDDE and RoadRunner's LLVM libraries can conflict on macOS.
    # Match the catalog runner's process isolation rather than depending on test order.
    code = '''
import numpy as np
from jitcdde import t, y
from grn_memory.scheper_delay import compiled_delay
times = np.linspace(0, 3, 31)
values = compiled_delay([y(0, t-1)], times, [1], 1, step=.001)
expected = 1+times+np.maximum(times-1, 0)**2/2+np.maximum(times-2, 0)**3/6
np.testing.assert_allclose(values[:, 0], expected, rtol=1e-7, atol=1e-9)
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_scheper_first_delay_window_uses_constant_prehistory():
    from pathlib import Path
    from grn_memory.scheper_delay import trajectory
    path = Path(__file__).resolve().parents[1] / "models/BIOMD0000000024.xml"
    times = np.linspace(0, 4, 41)
    result = trajectory(path, times, "scipy-method-of-steps")
    # Production is 1 until t=4 because delayed M is the initial concentration 1.
    expected = 1/.21+(1-1/.21)*np.exp(-.21*times)
    np.testing.assert_allclose(result.P, expected, rtol=1e-9, atol=1e-11)
    from grn_memory.simulation import model_info
    with pytest.raises(ValueError, match="history-preserving"):
        model_info(path)
