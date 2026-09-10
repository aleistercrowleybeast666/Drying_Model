from numba import njit


@njit(cache=True)
def Boundary_GetConductance(coefficient, distance, exchange):
    if exchange == 0:
        return 0.0
    return 1.0 / (distance/coefficient + 1.0/exchange)


@njit(cache=True)
def Boundary_Reconstruct(value, outside, coefficient, distance, exchange):
    if exchange == 0:
        return value
    flux = Boundary_GetConductance(coefficient, distance, exchange)*(value-outside)
    return outside + flux/exchange
