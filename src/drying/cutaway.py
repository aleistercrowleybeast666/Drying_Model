"""Upright cylinder cut transversely by an oblique plane through its midsection.

The removed upper portion exposes an elliptical cut. Model axial coordinates
and length are unchanged; only visibility is clipped. No axial stretching.
"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from scipy.interpolate import RegularGridInterpolator
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


def Cutaway_GetSurfaces(radius, half_length, angle_deg=45., azimuth_deg=35.):
    if radius <= 0 or half_length <= 0 or not 15 <= angle_deg <= 75:
        raise ValueError('CUTAWAY_RENDER_FAILED: invalid radius/plane angle')
    angle,azimuth=np.deg2rad([angle_deg,azimuth_deg])
    slope=1/np.tan(angle)  # plane-to-axis angle, not an axial longitudinal cut
    normal=np.array([-slope*np.cos(azimuth),-slope*np.sin(azimuth),1.])
    if radius*slope >= half_length:
        raise ValueError('CUTAWAY_RENDER_FAILED: plane intersects cylinder endcap')
    theta=np.linspace(0,2*np.pi,65)
    height,tt=np.meshgrid(np.linspace(0,1,33),theta,indexing='ij')
    xx,yy=radius*np.cos(tt),radius*np.sin(tt)
    top=slope*(xx*np.cos(azimuth)+yy*np.sin(azimuth))
    shell=(xx,yy,-half_length+height*(top+half_length))
    rr,tt=np.meshgrid(np.linspace(0,radius,25),theta,indexing='ij')
    xx,yy=rr*np.cos(tt),rr*np.sin(tt)
    cut=(xx,yy,slope*(xx*np.cos(azimuth)+yy*np.sin(azimuth)))
    bottom=(xx,yy,np.full_like(xx,-half_length))
    return dict(shell=shell,cut=cut,ends=[bottom],normal=normal,
        model_axial_limits=[-half_length,half_length],cut_center_z=0.)


def Cutaway_SampleSurface(r,z,nodes,surface,variable):
    xx,yy,zz=surface
    coordinates=np.column_stack((np.minimum(np.hypot(xx.ravel(),yy.ravel()),r[-1]),
                                  np.minimum(abs(zz.ravel()),z[-1])))
    values=RegularGridInterpolator((r,z),nodes[variable],bounds_error=True)(coordinates).reshape(xx.shape)
    return values-(273.15 if variable==0 else 0.)


def Cutaway_DrawFrame(index,datasets,progress,config):
    fig=plt.figure(figsize=(9.4,10.8),dpi=100,layout='constrained')
    fig.get_layout_engine().set(h_pad=.20,hspace=.12,w_pad=.04)
    axes=np.empty((2,2),dtype=object)
    boundary=max(1.8,config.get('boundary_width',1.8)); cut_width=max(2.2,config.get('cut_width',2.2))
    for p in [0,1]:
        for col,dataset in enumerate(datasets):
            axis=fig.add_subplot(2,2,p*2+col+1,projection='3d'); axes[p,col]=axis
            r,z,nodes=dataset['frames'][index]
            shape=Cutaway_GetSurfaces(r[-1],z[-1],config['angle_deg'],config.get('azimuth_deg',35.))
            limits=config.get('color_limits',[(28,53),(0,2.55)])[p]
            cmap=plt.get_cmap('inferno' if p==0 else 'viridis'); norm=Normalize(*limits)
            polygons=[]; colors=[]
            # The bottom cap faces away from this elevated camera. Culling it
            # avoids painter-order artefacts that look like a transparent tube.
            for surface in [shape['shell'],shape['cut']]:
                values=Cutaway_SampleSurface(r,z,nodes,surface,p)
                xyz=np.stack(surface,axis=-1)*100
                vertices=np.stack([xyz[:-1,:-1],xyz[1:,:-1],xyz[1:,1:],xyz[:-1,1:]],axis=-2).reshape(-1,4,3)
                average=(values[:-1,:-1]+values[1:,:-1]+values[1:,1:]+values[:-1,1:])/4
                polygons.append(vertices); colors.append(cmap(norm(average.ravel())))
            axis.add_collection3d(Poly3DCollection(np.concatenate(polygons),facecolors=np.concatenate(colors),
                edgecolors='none',linewidths=0,antialiased=False,zsort='average'))
            # Only physical boundaries, no dense surface mesh or artificial shading.
            axis.plot(*(c[-1,:]*100 for c in shape['cut']),color='#17212b',lw=cut_width,zorder=10)
            camera_azimuth=-55.
            arc=np.linspace(*np.deg2rad([camera_azimuth-90,camera_azimuth+90]),65)
            axis.plot(r[-1]*100*np.cos(arc),r[-1]*100*np.sin(arc),np.full_like(arc,-z[-1]*100),
                color='#17212b',lw=boundary,zorder=10)
            for theta in np.deg2rad([camera_azimuth-90,camera_azimuth+90]):
                x,y=r[-1]*np.cos(theta),r[-1]*np.sin(theta)
                top=-(shape['normal'][0]*x+shape['normal'][1]*y)
                axis.plot([x*100]*2,[y*100]*2,[-z[-1]*100,top*100],color='#17212b',lw=boundary,zorder=10)
            axis.set(xlim=(-2.2,2.2),ylim=(-2.2,2.2),zlim=(-12.5,2.5),
                xlabel='',ylabel='',zlabel='轴向 z / cm')
            axis.text2D(.02,.02,'x、y / cm',transform=axis.transAxes,fontsize=8)
            axis.set_xticks([-2,0,2]); axis.set_yticks([-2,0,2]); axis.set_zticks([-12,-8,-4,0])
            axis.set_box_aspect((4.4,4.4,15),zoom=.92)
            axis.view_init(elev=23,azim=camera_azimuth); axis.grid(False)
            axis.tick_params(labelsize=8,pad=0)
            axis.set_title(f'Q{dataset["question"]} {"温度" if p==0 else "含水率"}  t={dataset["times"][index]/3600:.3f} h\n'
                f'R={r[-1]*100:.4f} cm',fontsize=11,pad=8)
    for p in [0,1]:
        limits=config.get('color_limits',[(28,53),(0,2.55)])[p]
        fig.colorbar(ScalarMappable(norm=Normalize(*limits),cmap='inferno' if p==0 else 'viridis'),
            ax=axes[p,:].tolist(),shrink=.72,pad=.04,
            label='温度 / ℃' if p==0 else '干基含水率 C / (kg/kg)')
    fig.suptitle(f'真实二维场 · 竖直圆柱 · {config["angle_deg"]:g}° 斜砍 · 相对进度 {progress[index]*100:.1f}%\n'
        '按二维各自终点播放；移去上段仅作显示、模型长度不变；Q4 实际收缩',fontsize=12)
    return fig
