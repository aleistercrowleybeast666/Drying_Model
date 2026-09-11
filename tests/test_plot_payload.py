import json
import os
import subprocess
import sys
from pathlib import Path
import numpy as np
import pytest
from drying.plot_contract import Payload_ReadManifest, Payload_GetSeal
from drying.cutaway import Cutaway_GetSurfaces, Cutaway_SampleSurface
from drying.storage import Storage_WriteJson, Storage_HashFiles


def test_plot_import_boundary_has_no_solver_or_input_modules():
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    script="import drying.presentation, sys; assert not ({'drying.cases','drying.rk4','drying.inputs','drying.sampling','drying.plot_payload'} & set(sys.modules))"
    subprocess.run([sys.executable,'-c',script],env=env,check=True)


def test_manifest_missing_payload_version_and_integrity_errors_preserve_excel(tmp_path):
    with pytest.raises(FileNotFoundError,match='PLOT_MANIFEST_MISSING'):
        Payload_ReadManifest(tmp_path)
    table=tmp_path/'results/tables/result1.xlsx'; table.parent.mkdir(parents=True); table.write_bytes(b'untouched')
    info=dict(schema_version=1,payload_files=[dict(path='work/plot_payload/data.npz',hash='missing')],
        outputs=[],questions={},overview_payload='work/plot_payload/data.npz')
    path=tmp_path/'work/plot_payload/plot_manifest.json'
    info['manifest_hash']=Payload_GetSeal(info); Storage_WriteJson(path,info)
    with pytest.raises(FileNotFoundError,match='PLOT_PAYLOAD_MISSING.*data.npz'):
        Payload_ReadManifest(tmp_path)
    payload=tmp_path/'work/plot_payload/data.npz'; payload.write_bytes(b'payload')
    info['payload_files'][0]['hash']=Storage_HashFiles([payload]); info['manifest_hash']=Payload_GetSeal(info)
    Storage_WriteJson(path,info); assert Payload_ReadManifest(tmp_path)['schema_version']==1
    payload.write_bytes(b'tampered')
    with pytest.raises(RuntimeError,match='PLOT_DATA_VERSION_MISMATCH'):
        Payload_ReadManifest(tmp_path)
    info['schema_version']=999; info['manifest_hash']=Payload_GetSeal(info); Storage_WriteJson(path,info)
    with pytest.raises(RuntimeError,match='PLOT_DATA_VERSION_MISMATCH'):
        Payload_ReadManifest(tmp_path)
    assert table.read_bytes()==b'untouched'


def test_cut_plane_geometry_shrinks_and_samples_real_axial_field():
    large=Cutaway_GetSurfaces(.02,.125); small=Cutaway_GetSurfaces(.012,.125)
    for radius,shape in [(.02,large),(.012,small)]:
        x,y,z=shape['cut']
        np.testing.assert_allclose(shape['normal'][0]*x+shape['normal'][1]*y+shape['normal'][2]*z,0,atol=1e-17)
        assert np.nanmax(np.hypot(x,y)) <= radius+1e-15
        assert np.nanmax(abs(z))<=radius+1e-15
        assert np.min(shape['shell'][2])==-.125
        assert shape['model_axial_limits']==[-.125,.125]
        assert abs(shape['normal'][2]/np.linalg.norm(shape['normal'])-np.sqrt(.5))<1e-14
        r,axial=np.linspace(0,radius,41),np.linspace(0,.125,126)
        rr,zz=np.meshgrid(r,axial,indexing='ij')
        nodes=np.stack([300+2*rr+3*zz,1+rr+zz])
        values=Cutaway_SampleSurface(r,axial,nodes,shape['cut'],1)
        np.testing.assert_allclose(values,1+np.hypot(x,y)+abs(z),rtol=1e-14)
    assert np.nanmax(np.hypot(*small['cut'][:2])) < np.nanmax(np.hypot(*large['cut'][:2]))
