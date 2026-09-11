import numpy as np
from numba import njit
from .materials import Material_Evaluate
from .boundaries import Boundary_Reconstruct
from .inputs import Input_AtTime
from .geometry import Geometry_GetGrid, Geometry_GetSymmetryWeights


@njit(cache=True)
def Sampling_Reconstruct(U, R, Te, He, model, h=25., hm=8e-7, ends=True, xi_faces=None, eta_faces=None):
    nr, nz = U.shape[1:]
    rf,rc,dr,zf,zc,dz = Geometry_GetGrid(nr,nz,R,xi_faces,eta_faces)
    ar,br = Geometry_GetSymmetryWeights(rf,True)
    az,bz = Geometry_GetSymmetryWeights(zf,False) if nz>1 else (1.,0.)
    field = np.empty((2, nr+2, nz+2), dtype=np.float64)
    field[:, 1:-1, 1:-1] = U
    for j in range(nz):
        properties = Material_Evaluate(model, U[0, -1, j], U[1, -1, j])
        for p in range(2):
            field[p, 0, j+1] = ar*U[p, 0, j]+br*U[p, 1, j]
            field[p, -1, j+1] = Boundary_Reconstruct(U[p, -1, j], Te if p == 0 else He,
                properties[p+2], R-rc[-1], h if p == 0 else hm)
    for i in range(nr+2):
        properties = Material_Evaluate(model, field[0, i, -2], field[1, i, -2])
        for p in range(2):
            if nz == 1:
                field[p, i, 0] = field[p, i, 1]
                field[p, i, -1] = field[p, i, 1]
            else:
                field[p, i, 0] = az*field[p, i, 1]+bz*field[p, i, 2]
                field[p, i, -1] = Boundary_Reconstruct(field[p, i, -2], Te if p == 0 else He,
                    properties[p+2], zf[-1]-zc[-1], (h if p == 0 else hm) if ends else 0.)
    if nz > 1:
        # Axis/end and axis/midplane use the same annular-average quadratic.
        for p in range(2):
            field[p, 0, -1] = ar*field[p, 1, -1]+br*field[p, 2, -1]
        # Corner: average radial-then-axial and axial-then-radial reconstruction.
        properties = Material_Evaluate(model, field[0, -2, -1], field[1, -2, -1])
        for p in range(2):
            other = Boundary_Reconstruct(field[p, -2, -1], Te if p == 0 else He,
                properties[p+2], R-rc[-1], h if p == 0 else hm)
            field[p, -1, -1] = (field[p, -1, -1]+other)/2
    return field


@njit(cache=True)
def Sampling_MaxMoisture(U, He, xi_faces=None, eta_faces=None):
    # All boundary values are convex combinations of adjacent reconstructed
    # values and He. Piecewise-linear interpolation has no additional extrema.
    nr, nz = U.shape[1:]
    rf,rc,dr,zf,zc,dz = Geometry_GetGrid(nr,nz,1.,xi_faces,eta_faces)
    ar,br = Geometry_GetSymmetryWeights(rf,True)
    az,bz = Geometry_GetSymmetryWeights(zf,False) if nz>1 else (1.,0.)
    value, ii, jj = He, -1, -1
    for i in range(nr):
        for j in range(nz):
            if U[1, i, j] > value:
                value, ii, jj = U[1, i, j], i, j
    for j in range(nz):
        axis = ar*U[1, 0, j]+br*U[1, 1, j]
        if axis > value:
            value, ii, jj = axis, -1, j
    if nz > 1:
        for i in range(nr):
            middle = az*U[1, i, 0]+bz*U[1, i, 1]
            if middle > value:
                value, ii, jj = middle, i, -1
        center = az*(ar*U[1, 0, 0]+br*U[1, 1, 0])+bz*(ar*U[1, 0, 1]+br*U[1, 1, 1])
        if center > value:
            value, ii, jj = center, -1, -1
    return value, ii, jj


def Sampling_GetNodes(U, t, model, inputs, mesh=None):
    Te, He, R = Input_AtTime(t, *inputs, model == 4)
    nr, nz = U.shape[1:]
    xi,eta = mesh if mesh is not None else (None,None)
    rf,rc,dr,zf,zc,dz = Geometry_GetGrid(nr,nz,R,xi,eta)
    r,z = np.r_[0.,rc,R],np.r_[0.,zc,zf[-1]]
    values = Sampling_Reconstruct(U, R, Te, He, model, ends=nz > 1,xi_faces=xi,eta_faces=eta)
    if t == 0:
        values[:] = U[:, :1, :1]
    return r, z, values


def Sampling_GetRadial(U, t, model, inputs, positions, mesh=None):
    r, _, values = Sampling_GetNodes(U, t, model, inputs, mesh)
    positions = np.asarray(positions)
    valid = positions <= r[-1] + 1e-14
    sampled = np.full((2, len(positions)), np.nan)
    for p in range(2):
        sampled[p, valid] = np.interp(positions[valid], r, values[p, :, 0])
    return sampled, valid, values[:, -1, 0], r[-1]
