"""Cell-average finite volumes: common-face flux once; V*dU/dt, including shrinkage."""
import numpy as np
from numba import njit
from .materials import Material_Evaluate
from .boundaries import Boundary_GetConductance


@njit(cache=True)
def Operator_Evaluate(U, R, Te, He, model, h, hm, ends, out, props, rows, constant):
    nr, nz = U.shape[1:]
    dr, dz = R/nr, 0.125/nz
    out[:] = 0.0
    rows[:] = 0.0
    for i in range(nr):
        for j in range(nz):
            T, C = U[0, i, j], U[1, i, j]
            if not np.isfinite(T) or not np.isfinite(C):
                return 0.0, 1, i, j
            if C <= 0 or T <= 0:
                return 0.0, 2, i, j
            values = Material_Evaluate(model, T, C)
            for p in range(4):
                props[p, i, j] = constant[p] if constant[0] > 0 else values[p]
                if props[p, i, j] <= 0 or not np.isfinite(props[p, i, j]):
                    return 0.0, 3, i, j
    # Per-radian geometry. Multiplying every area/volume by 2*pi cancels.
    for i in range(nr-1):
        area = (i+1)*dr*dz
        for j in range(nz):
            for field in range(2):
                a, b = props[field+2, i, j], props[field+2, i+1, j]
                conductance = area * (2*a*b/(a+b)) / dr
                flux = conductance*(U[field, i+1, j]-U[field, i, j])
                out[field, i, j] += flux
                out[field, i+1, j] -= flux
                rows[field, i, j] += conductance
                rows[field, i+1, j] += conductance
    if nz > 1:
        for i in range(nr):
            area = (i+0.5)*dr*dr
            for j in range(nz-1):
                for field in range(2):
                    a, b = props[field+2, i, j], props[field+2, i, j+1]
                    conductance = area*(2*a*b/(a+b))/dz
                    flux = conductance*(U[field, i, j+1]-U[field, i, j])
                    out[field, i, j] += flux
                    out[field, i, j+1] -= flux
                    rows[field, i, j] += conductance
                    rows[field, i, j+1] += conductance
    for j in range(nz):
        for field in range(2):
            outside = Te if field == 0 else He
            exchange = h if field == 0 else hm
            conductance = R*dz*Boundary_GetConductance(props[field+2, nr-1, j], dr/2, exchange)
            out[field, nr-1, j] -= conductance*(U[field, nr-1, j]-outside)
            rows[field, nr-1, j] += conductance
    if ends:
        for i in range(nr):
            area = (i+0.5)*dr*dr
            for field in range(2):
                outside = Te if field == 0 else He
                exchange = h if field == 0 else hm
                conductance = area*Boundary_GetConductance(props[field+2, i, nz-1], dz/2, exchange)
                out[field, i, nz-1] -= conductance*(U[field, i, nz-1]-outside)
                rows[field, i, nz-1] += conductance
    largest_row = 0.0
    for i in range(nr):
        volume = (i+0.5)*dr*dr*dz
        for j in range(nz):
            for field in range(2):
                capacity = props[0, i, j]*props[1, i, j] if field == 0 else 1.0
                denominator = volume*capacity
                out[field, i, j] /= denominator
                rows[field, i, j] /= denominator
                largest_row = max(largest_row, rows[field, i, j])
    return largest_row, 0, -1, -1
