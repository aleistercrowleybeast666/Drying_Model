"""Single authoritative implementation of the problem's empirical properties (SI)."""
import numpy as np
from numba import njit


@njit(cache=True)
def Material_Evaluate(model, T, C):
    if model == 1:
        return 820.0, 2600.0, 0.36, 7e-9 * np.exp(-0.89 / C)
    if model == 3:
        return (650 + 128*C, 1450 + 2736*C/(1+C),
                0.21 + 0.38*C/(1+C), 2.4e-3*np.exp(-0.45/C - 3850/T))
    if model == 4:
        return (760 + 90*C, 1850 + 2150*C/(1+C),
                0.12 + 0.20*C/(1+C), 4.2e-4*np.exp(-0.30/C - 3850/T))
    raise ValueError("SOURCE_FORMULA_MISMATCH: unknown material appendix")
