import numpy as np
from numba import njit


@njit(cache=True)
def Geometry_GetGrid(nr,nz,R,xi_faces=None,eta_faces=None,half_length=.125):
    xi = np.linspace(0.,1.,nr+1) if xi_faces is None else xi_faces
    eta = np.linspace(0.,1.,nz+1) if eta_faces is None else eta_faces
    rf,zf = R*xi,half_length*eta
    return rf,(rf[:-1]+rf[1:])/2,np.diff(rf),zf,(zf[:-1]+zf[1:])/2,np.diff(zf)


def Geometry_GetCells(nr,nz,R,half_length=.125,mesh=None):
    rf,rc,dr,zf,zc,dz = Geometry_GetGrid(nr,nz,R,*(mesh if mesh is not None else (None,None)),half_length)
    volumes = np.pi*np.diff(rf**2)[:,None]*dz[None,:]
    return rc,zc,volumes


@njit(cache=True)
def Geometry_GetSymmetryWeights(faces,radial):
    # For a + b*x^2, FV averages use the exact second moment in each cell.
    if radial:
        m0=(faces[0]**2+faces[1]**2)/2
        m1=(faces[1]**2+faces[2]**2)/2
    else:
        m0=(faces[0]**2+faces[0]*faces[1]+faces[1]**2)/3
        m1=(faces[1]**2+faces[1]*faces[2]+faces[2]**2)/3
    return m1/(m1-m0),-m0/(m1-m0)
