import numpy as np


def Geometry_GetCells(nr, nz, R, half_length=0.125):
    faces = np.linspace(0, R, nr+1)
    dr, dz = R/nr, half_length/nz
    volumes = np.pi*np.diff(faces**2)[:, None]*np.full((1, nz), dz)
    return (faces[:-1]+dr/2, (np.arange(nz)+0.5)*dz, volumes)
