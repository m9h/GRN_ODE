"""An exact delayed response to a jump checks preservation of pre-jump history."""

import importlib.util
import subprocess
import sys

import numpy as np
import pytest

from grn_memory.delay_protocols import steps_with_resets


def expected(times):
    return np.where(times < .5, 1+times,
           np.where(times < 1, 4.5+times,
           np.where(times < 1.5, 5+times**2/2,
                    6.125+(times**2-2.25)/2+3.5*(times-1.5))))


def test_delay_jump_keeps_prior_history():
    times = np.linspace(0, 2, 41)
    values = steps_with_resets(lambda t, state, past: past, times, [1.], 1., {.5: {0: 5.}})
    np.testing.assert_allclose(values[:, 0], expected(times), rtol=1e-9, atol=1e-10)


def test_jitcdde_jump_against_exact_piecewise_solution():
    if importlib.util.find_spec("jitcdde") is None:
        pytest.skip("Optional delay engine not installed")
    code = '''
import numpy as np
from jitcdde import t, y
from grn_memory.delay_protocols import jitcdde_with_resets
times = np.linspace(0, 2, 41)
expected = np.where(times < .5, 1+times, np.where(times < 1, 4.5+times,
           np.where(times < 1.5, 5+times**2/2, 6.125+(times**2-2.25)/2+3.5*(times-1.5))))
values = jitcdde_with_resets([y(0,t-1)], times, [1.], 1., {.5: {0:5.}}, step=.001)
np.testing.assert_allclose(values[:,0], expected, rtol=1e-7, atol=1e-8)
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
