import json
import os
import subprocess
import sys
from pathlib import Path
import numpy as np
import pytest
from drying.plot_contract import Payload_ReadManifest, Payload_GetSeal
from drying.cutaway import Cutaway_GetSurfaces, Cutaway_SampleSurface, Cutaway_ClipDisplay, Cutaway_GetView, Cutaway_DrawFrame, Cutaway_GetContours
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


def test_cutaway_crop_preserves_visible_coordinates_and_physical_sampling():
    original=Cutaway_GetSurfaces(.02,.125)
    cropped=Cutaway_ClipDisplay(original)
    assert cropped['display_lower_z']==-.0625
    assert cropped['model_axial_limits']==[-.125,.125]
    assert original['shell'][2].min()==-.125
    for before,after in zip(original['cut'],cropped['cut']):
        np.testing.assert_array_equal(before,after)
    visible=original['shell'][2]>=-.0625
    np.testing.assert_array_equal(original['shell'][2][visible],cropped['shell'][2][visible])
    r,z=np.linspace(0,.02,41),np.linspace(0,.125,126)
    rr,zz=np.meshgrid(r,z,indexing='ij')
    nodes=np.stack([300+2*rr+3*zz,1+rr+zz])
    x,y,axial=cropped['shell']
    np.testing.assert_allclose(Cutaway_SampleSurface(r,z,nodes,cropped['shell'],1),
                               1+np.hypot(x,y)+abs(axial),rtol=1e-14)


def test_cutaway_camera_layout_fixed_scales_and_real_radius():
    import matplotlib.pyplot as plt
    plt.switch_backend('Agg')
    config=dict(angle_deg=45,azimuth_deg=35)
    view=Cutaway_GetView(config)
    assert view['camera_yaw_deg']==-145 and view['camera_elevation_deg']==23
    normal=Cutaway_GetSurfaces(.02,.125)['normal']
    yaw,elev=np.deg2rad([view['camera_yaw_deg'],view['camera_elevation_deg']])
    camera=np.array([np.cos(elev)*np.cos(yaw),np.cos(elev)*np.sin(yaw),np.sin(elev)])
    assert np.dot(camera,normal/np.linalg.norm(normal))>.92  # Within 23 degrees of face-on.
    datasets=[]
    for q,radius in [(3,.02),(4,.012)]:
        r,z=np.linspace(0,radius,5),np.linspace(0,.125,9)
        datasets.append(dict(question=q,times=np.array([3600.*q]),frames=[(r,z,np.ones((2,5,9))*300)]))
    fig=Cutaway_DrawFrame(0,datasets,[.5],config)
    try:
        assert '前 6% 慢放' in fig._suptitle.get_text() and '0.5 倍速' in fig._suptitle.get_text()
        axes=[a for a in fig.axes if a.name=='3d']
        assert [a.get_title().split('  ')[0] for a in axes]==['Q3 温度','Q4 温度','Q3 含水率','Q4 含水率']
        for i,axis in enumerate(axes):
            assert axis.azim==-145 and axis.elev==23
            assert axis.get_zlim()==(-6.25,2.5)
            np.testing.assert_allclose(axis.get_box_aspect()/np.array([4.4,4.4,8.75]),
                                       np.repeat(axis.get_box_aspect()[0]/4.4,3))
            x,y,z=axis.lines[0].get_data_3d()
            np.testing.assert_allclose(np.hypot(x,y),2 if i%2==0 else 1.2)
            assert axis.lines[0].get_linewidth()==1.4
            assert all(line.get_linewidth()==1.1 for line in axis.lines[1:])
            assert all(line.get_path_effects() for line in axis.lines)
        # Row colour bars retain the shared, time-independent normalizations.
        assert fig.axes[-2].get_ylim()==(28,53)
        assert fig.axes[-1].get_ylim()==(0,2.55)
    finally:
        plt.close(fig)


def test_plot_does_not_republish_stale_overview(tmp_path,monkeypatch):
    import drying.presentation as presentation
    current={'results/overview.md':'current production PASS',
             'results/status.json':'current status'}
    current.update({f'results/q{q}/q{q}_summary.json':f'current Q{q}' for q in range(1,5)})
    for name,text in current.items():
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    stale=tmp_path/'work/plot_payload/overview_data.json'
    stale.parent.mkdir(parents=True);stale.write_text('{"status":"old fixed FAIL"}')
    manifest=dict(outputs=[],color_limits=dict(temperature_C=[28,53],moisture_kg_kg=[0,2.55]),
                  overview_payload='work/plot_payload/overview_data.json',manifest_hash='snapshot')
    monkeypatch.setattr(presentation,'Payload_ReadManifest',lambda _:manifest)
    monkeypatch.setattr(presentation,'Payload_GetRenderHash',lambda _:'render')
    presentation.Presentation_Run(tmp_path,png=False,gif=False)
    assert all((tmp_path/name).read_text()==text for name,text in current.items())


@pytest.mark.parametrize('radius',[.02,.012])
@pytest.mark.parametrize('variable',[0,1])
def test_cutaway_isolines_follow_field_on_unchanged_plane(radius,variable):
    r,z=np.linspace(0,radius,41),np.linspace(0,.125,126)
    rr,zz=np.meshgrid(r,z,indexing='ij')
    nodes=np.stack([300+100*rr+3*zz,.2+20*rr+3*zz])
    normal=Cutaway_GetSurfaces(radius,.125)['normal']
    levels=np.arange(26.,30.,.5) if variable==0 else np.arange(.1,.81,.1)
    contours=Cutaway_GetContours(r,z,nodes,normal,variable,levels)
    assert contours
    for contour in contours:
        assert np.min(abs(levels-contour['level']))<1e-14
        for points in contour['paths']:
            np.testing.assert_allclose(points@normal,0,atol=1e-16)
            assert np.max(np.hypot(points[:,0],points[:,1]))<=radius+1e-14
            # Linear interpolation of a smooth curved contour has only the
            # rendering tessellation's small chord error, not a displaced plane.
            offset,factor,tolerance=(26.85,100,1e-3) if variable==0 else (.2,20,2e-4)
            field=offset+factor*np.hypot(points[:,0],points[:,1])+3*abs(points[:,2])
            np.testing.assert_allclose(field,contour['level'],atol=tolerance)
    assert Cutaway_GetContours(r,z,np.ones_like(nodes),normal,variable,levels)==[]


def test_gif_half_speed_doubles_encoded_delays_without_changing_frames(tmp_path):
    import matplotlib.pyplot as plt
    from PIL import Image
    from drying.animations import Animation_WriteGif
    plt.switch_backend('Agg')
    def Draw(index):
        return plt.figure(figsize=(1,1),dpi=20,facecolor=['red','green','blue'][index])
    durations=[];pixels=[]
    for speed in [1.,.5]:
        path=tmp_path/f'speed_{speed}.gif'
        record=Animation_WriteGif(tmp_path,path,3,24,Draw,{},playback_rate=speed)
        times=[];frames=[]
        with Image.open(path) as gif:
            for index in range(gif.n_frames):
                gif.seek(index);times.append(gif.info['duration']);frames.append(np.array(gif.convert('RGB')))
        assert record['total_duration_ms']==sum(times)
        durations.append(times);pixels.append(frames)
    assert durations==[[40,40,1000],[80,80,2000]]
    np.testing.assert_array_equal(pixels[0],pixels[1])
