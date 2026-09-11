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
from matplotlib import patheffects
from contourpy import contour_generator


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


def Cutaway_ClipDisplay(shape):
    """Intersect the visible shell with z >= -L/4; keep physical coordinates.

    Clipped-away quads collapse at the display boundary. Every vertex above
    that boundary and the entire oblique face remain exactly where they were.
    The new lower contour is a display crop, not a physical endcap.
    """
    lower=shape['model_axial_limits'][0]/2
    x,y,z=shape['shell']
    return dict(shape,shell=(x,y,np.maximum(z,lower)),display_lower_z=lower)


def Cutaway_GetView(config):
    # Opposite the plane's horizontal gradient: its exposed face faces the camera.
    # Only yaw changes. Plane angle/azimuth and the 23-degree elevation stay fixed.
    yaw=(config.get('azimuth_deg',35.) % 360)-180.
    return dict(camera_yaw_deg=yaw,camera_elevation_deg=23.,lower_half_crop_fraction=.5,
        boundary_width=1.1,cut_width=1.4,size_px=[1080,960],playback_rate=.5,
        contour_width=.6,contour_temperature_interval_C=.5,contour_moisture_interval=.1,
        contour_scope='actual oblique face; fixed equal-value levels shared by Q3/Q4 and every frame',
        physical_axis_scale='equal; no axial compression')


def Cutaway_GetContours(r,z,nodes,normal,variable,levels):
    """Extract isolines from the unchanged field on the actual oblique plane.

    The polar sampling mesh is only a rendering tessellation. Contours follow
    scalar values, never a geometric decoration or a per-frame normalization.
    """
    rr,theta=np.meshgrid(np.linspace(0,r[-1],97),np.linspace(0,2*np.pi,129),indexing='ij')
    x,y=rr*np.cos(theta),rr*np.sin(theta)
    axial=-(normal[0]*x+normal[1]*y)/normal[2]
    values=Cutaway_SampleSurface(r,z,nodes,(x,y,axial),variable)
    lower,upper=float(values.min()),float(values.max())
    if upper-lower<1e-8:
        return []  # A uniform field has no isolines to draw.
    generator=contour_generator(x=x,y=y,z=values,name='serial')
    contours=[]
    for level in levels:
        if not lower+1e-10<level<upper-1e-10:
            continue
        paths=[]
        for xy in generator.lines(float(level)):
            if len(xy)<2:
                continue
            zz=-(normal[0]*xy[:,0]+normal[1]*xy[:,1])/normal[2]
            paths.append(np.column_stack([xy,zz]))
        if paths:
            contours.append(dict(level=float(level),paths=paths))
    return contours


def Cutaway_DrawContours(axis,contours,radius,normal,view,cmap,norm):
    candidates=[]
    for contour in contours:
        rgb=cmap(norm(contour['level']))[:3]
        color='#f1f5f9' if np.dot(rgb,[.2126,.7152,.0722])<.45 else '#24313e'
        for path in contour['paths']:
            line,=axis.plot(*(path*100).T,color=color,lw=view['contour_width'],alpha=.9,zorder=11)
            line.set_gid('cutaway_isoline')
        path=max(contour['paths'],key=lambda points:np.linalg.norm(np.diff(points,axis=0),axis=1).sum())
        # Leave room between a label and the face boundary; very small central
        # loops and steep near-surface gradients still get lines without text.
        distance=np.hypot(path[:,0],path[:,1])
        eligible=path[(distance>.18*radius)&(distance<.86*radius)]
        if len(eligible): candidates.append((contour['level'],eligible))
    if not candidates:
        return
    azimuth=np.arctan2(-normal[1],-normal[0])
    for sector,index in enumerate(np.unique(np.linspace(0,len(candidates)-1,min(3,len(candidates)),dtype=int))):
        level,path=candidates[index]
        bearing=azimuth+sector*2*np.pi/3
        point=path[np.argmax(np.cos(np.arctan2(path[:,1],path[:,0])-bearing))]
        label=axis.text(*(point*100),f'{level:g}',fontsize=7,ha='center',va='center',zorder=13,
            color='#17212b',bbox=dict(boxstyle='round,pad=.08',facecolor='white',edgecolor='none',alpha=.88))
        label.set_gid('cutaway_isoline_label')


def Cutaway_DrawFrame(index,datasets,progress,config):
    view=Cutaway_GetView(config)
    fig=plt.figure(figsize=tuple(v/100 for v in view['size_px']),dpi=100,layout='constrained')
    fig.get_layout_engine().set(h_pad=.16,hspace=.16,w_pad=.04)
    axes=np.empty((2,2),dtype=object)
    boundary=view['boundary_width']; cut_width=view['cut_width']
    half_length=datasets[0]['frames'][0][1][-1]
    lower_cm=-half_length*50
    for p in [0,1]:
        for col,dataset in enumerate(datasets):
            axis=fig.add_subplot(2,2,p*2+col+1,projection='3d'); axes[p,col]=axis
            r,z,nodes=dataset['frames'][index]
            shape=Cutaway_ClipDisplay(Cutaway_GetSurfaces(r[-1],z[-1],config['angle_deg'],config.get('azimuth_deg',35.)))
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
            # Fine cut edge, silhouette and visible display-crop contour; no mesh.
            axis.plot(*(c[-1,:]*100 for c in shape['cut']),color='#17212b',lw=cut_width,zorder=12)
            camera_azimuth=view['camera_yaw_deg']
            arc=np.linspace(*np.deg2rad([camera_azimuth-90,camera_azimuth+90]),65)
            axis.plot(r[-1]*100*np.cos(arc),r[-1]*100*np.sin(arc),np.full_like(arc,shape['display_lower_z']*100),
                color='#17212b',lw=boundary,zorder=10)
            for theta in np.deg2rad([camera_azimuth-90,camera_azimuth+90]):
                x,y=r[-1]*np.cos(theta),r[-1]*np.sin(theta)
                top=-(shape['normal'][0]*x+shape['normal'][1]*y)
                axis.plot([x*100]*2,[y*100]*2,[shape['display_lower_z']*100,top*100],color='#17212b',lw=boundary,zorder=10)
            axis.set(xlim=(-2.2,2.2),ylim=(-2.2,2.2),zlim=(lower_cm,2.5),
                xlabel='',ylabel='',zlabel='轴向 z / cm')
            axis.text2D(.02,.02,'x、y / cm',transform=axis.transAxes,fontsize=8)
            axis.set_xticks([-2,0,2]); axis.set_yticks([-2,0,2]); axis.set_zticks([-6,-4,-2,0,2])
            axis.set_box_aspect((4.4,4.4,2.5-lower_cm),zoom=.96)
            axis.view_init(elev=view['camera_elevation_deg'],azim=camera_azimuth); axis.grid(False)
            for line in axis.lines:
                # A narrow light halo keeps the dark edge legible on low-C purple.
                line.set_gid('cutaway_boundary')
                line.set_path_effects([patheffects.Stroke(linewidth=line.get_linewidth()+.4,foreground='#f8fafc'),
                                       patheffects.Normal()])
            interval=view['contour_temperature_interval_C' if p==0 else 'contour_moisture_interval']
            levels=np.arange(np.ceil(limits[0]/interval),np.floor(limits[1]/interval)+1)*interval
            contours=Cutaway_GetContours(r,z,nodes,shape['normal'],p,levels)
            Cutaway_DrawContours(axis,contours,r[-1],shape['normal'],view,cmap,norm)
            axis.tick_params(labelsize=8,pad=0)
            axis.tick_params(axis='x',pad=-3); axis.tick_params(axis='y',pad=-3)
            axis.set_title(f'Q{dataset["question"]} {"温度" if p==0 else "含水率"}  t={dataset["times"][index]/3600:.3f} h\n'
                f'R={r[-1]*100:.4f} cm',fontsize=11,pad=8)
    for p in [0,1]:
        limits=config.get('color_limits',[(28,53),(0,2.55)])[p]
        fig.colorbar(ScalarMappable(norm=Normalize(*limits),cmap='inferno' if p==0 else 'viridis'),
            ax=axes[p,:].tolist(),shrink=.72,pad=.04,
            label='温度 / ℃（等值距 0.5 ℃）' if p==0 else '干基含水率 C / (kg/kg)（等值距 0.1）')
    fig.suptitle(f'真实二维场 · 竖直圆柱 · {config["angle_deg"]:g}° 斜砍 · 相对进度 {progress[index]*100:.1f}%'
        f' · 前 6% 慢放 · {view["playback_rate"]:g} 倍速\n'
        f'按二维各自终点播放；显示 z ≥ {lower_cm:g} cm（下段裁去 50%，轴向比例不变）；Q4 实际收缩',fontsize=12)
    return fig
