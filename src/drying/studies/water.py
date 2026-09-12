"""One bounded SI interface for IAPWS-IF97 saturation-path enthalpies."""
from functools import lru_cache
from pathlib import Path
import numpy as np
from numba import njit
from ..storage import Storage_WriteArray, Storage_WriteJson
from .baseline import Baseline_ReadJson, Baseline_HashFile


def Water_Prepare(root):
    import iapws
    from iapws import IAPWS97
    root=Path(root);folder=root/'work/studies/diagnostics';folder.mkdir(parents=True,exist_ok=True)
    path=folder/'water_properties.json';table=folder/'water_properties.npz'
    if path.exists():
        saved=Baseline_ReadJson(path)
        if saved['library_version']==iapws.__version__ and Baseline_HashFile(table)==saved['table_sha256']:return saved
    temperatures=np.linspace(273.16,373.15,1001)
    liquid=np.array([IAPWS97(T=float(t),x=0).h*1000 for t in temperatures])
    vapor=np.array([IAPWS97(T=float(t),x=1).h*1000 for t in temperatures]);latent=vapor-liquid
    mid=(temperatures[:-1]+temperatures[1:])/2
    truth_l=np.array([IAPWS97(T=float(t),x=0).h*1000 for t in mid])
    truth_v=np.array([IAPWS97(T=float(t),x=1).h*1000 for t in mid])
    errors=[float(np.max(np.abs(np.interp(mid,temperatures,liquid)-truth_l))),
            float(np.max(np.abs(np.interp(mid,temperatures,latent)-(truth_v-truth_l))))]
    if not 2.2e6<np.min(latent)<np.max(latent)<2.6e6:raise RuntimeError('WATER_PROPERTY_UNIT_ERROR')
    if max(errors)>.1:raise RuntimeError('WATER_PROPERTY_INTERPOLATION_FAILED')
    Storage_WriteArray(table,temperature_K=temperatures,liquid_h_J_kg=liquid,latent_h_J_kg=latent)
    result=dict(library='iapws',library_version=iapws.__version__,formulation='IAPWS-IF97',
        state_path='saturation at T; x=0 liquid, x=1 vapor; Lv=hv-hl',temperature_range_K=[273.16,373.15],
        units=dict(temperature='K',liquid_enthalpy='J/kg',latent_heat='J/kg'),conversion='IAPWS h [kJ/kg] multiplied by 1000',
        interpolation='piecewise linear, 1001 nodes; all 1000 interval midpoints independently checked',
        interpolation_max_abs_J_kg=dict(hl=errors[0],Lv=errors[1]),
        derivative='dhl/dT along the saturation path, not constant-pressure cp',
        out_of_range='THERMAL_MODEL_OUT_OF_DOMAIN; no clipping, extrapolation or ice model',
        sources=['https://iapws.org/technical-guidance/release/IF97-Rev','https://iapws.readthedocs.io/en/stable/iapws.iapws97.html'],
        implementation_sha256=Baseline_HashFile(Path(iapws.__file__).parent/'iapws97.py'),
        table_path=table.relative_to(root).as_posix(),table_sha256=Baseline_HashFile(table))
    Storage_WriteJson(path,result);return result


@njit(cache=True)
def Water_GetValue(T,grid,values):
    if not np.isfinite(T) or T<grid[0] or T>grid[-1]:return np.nan,np.nan
    i=min(int((T-grid[0])/(grid[1]-grid[0])),len(grid)-2)
    slope=(values[i+1]-values[i])/(grid[i+1]-grid[i])
    return values[i]+(T-grid[i])*slope,slope


@lru_cache(maxsize=4)
def Water_LoadTable(path,expected_hash):
    if Baseline_HashFile(path)!=expected_hash:raise RuntimeError('WATER_PROPERTY_TABLE_MISMATCH')
    with np.load(path) as data:return tuple(data[k].copy() for k in ['temperature_K','liquid_h_J_kg','latent_h_J_kg'])
