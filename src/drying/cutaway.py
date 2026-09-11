"""Oblique planar cut of a revolved axisymmetric field, with real SI geometry."""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from scipy.interpolate import RegularGridInterpolator
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


def Cutaway_GetSurfaces(radius, half_length, angle_deg=35., axial_tilt_deg=4.):
    if radius <= 0 or not 0 < angle_deg < 90 or not 0 <= axial_tilt_deg < 30:
        raise ValueError('CUTAWAY_RENDER_FAILED: invalid radius/plane angle')
    angle,tilt = np.deg2rad([angle_deg,axial_tilt_deg])
    normal = np.array([np.sin(tilt),np.cos(tilt)*np.cos(angle),np.cos(tilt)*np.sin(angle)])
    axial = np.linspace(-half_length,half_length,49)
    theta = np.linspace(0,2*np.pi,49)
    xx,tt = np.meshgrid(axial,theta,indexing='ij')
    yy,zz = radius*np.cos(tt),radius*np.sin(tt)
    keep = normal[0]*xx+normal[1]*yy+normal[2]*zz <= 1e-14
    shell = tuple(np.where(keep,c,np.nan) for c in (xx,yy,zz))
    # Exact chord of the oblique plane at each axial coordinate, including Q4 shrink.
    xx,uu = np.meshgrid(axial,np.linspace(-1,1,33),indexing='ij')
    offset = -np.tan(tilt)*xx
    half_chord = np.sqrt(np.maximum(0.,radius**2-offset**2))
    yy = offset*np.cos(angle)-uu*half_chord*np.sin(angle)
    zz = offset*np.sin(angle)+uu*half_chord*np.cos(angle)
    cut = tuple(np.where(abs(offset) <= radius,c,np.nan) for c in (xx,yy,zz))
    ends = []
    rr,tt = np.meshgrid(np.linspace(0,radius,17),theta,indexing='ij')
    for end in [-half_length,half_length]:
        xx = np.full_like(rr,end); yy,zz = rr*np.cos(tt),rr*np.sin(tt)
        keep = normal[0]*xx+normal[1]*yy+normal[2]*zz <= 1e-14
        ends.append(tuple(np.where(keep,c,np.nan) for c in (xx,yy,zz)))
    return dict(shell=shell,cut=cut,ends=ends,normal=normal)


def Cutaway_SampleSurface(r,z,nodes,surface,variable):
    xx,yy,zz = surface
    valid = np.isfinite(xx)&np.isfinite(yy)&np.isfinite(zz)
    values = np.zeros(xx.shape)
    # abs(x) unfolds the actual midplane symmetry, not a constant axial copy.
    coordinates = np.column_stack((np.minimum(np.hypot(yy[valid],zz[valid]),r[-1]),np.minimum(abs(xx[valid]),z[-1])))
    values[valid] = RegularGridInterpolator((r,z),nodes[variable],bounds_error=True)(coordinates)
    return values-(273.15 if variable == 0 else 0.)


def Cutaway_DrawFrame(index,datasets,progress,config):
    fig = plt.figure(figsize=(11,6.4),dpi=100,layout='constrained')
    axes = np.empty((2,2),dtype=object)
    for p in [0,1]:
        for col,dataset in enumerate(datasets):
            axis = fig.add_subplot(2,2,p*2+col+1,projection='3d'); axes[p,col] = axis
            r,z,nodes = dataset['frames'][index]
            shape = Cutaway_GetSurfaces(r[-1],z[-1],config['angle_deg'],config['axial_tilt_deg'])
            limits = config.get('color_limits',[(28,53),(0,2.55)])[p]
            cmap = plt.get_cmap('inferno' if p == 0 else 'viridis'); norm = Normalize(*limits)
            polygons=[]; colors=[]
            for surface in [shape['shell'],*shape['ends'],shape['cut']]:
                values = Cutaway_SampleSurface(r,z,nodes,surface,p)
                xyz=np.stack(surface,axis=-1)*100
                vertices=np.stack([xyz[:-1,:-1],xyz[1:,:-1],xyz[1:,1:],xyz[:-1,1:]],axis=-2).reshape(-1,4,3)
                valid=np.isfinite(vertices).all(axis=(1,2))
                average=(values[:-1,:-1]+values[1:,:-1]+values[1:,1:]+values[:-1,1:])/4
                polygons.append(vertices[valid]); colors.append(cmap(norm(average.ravel()[valid])))
            # A single collection sorts all shell/cap/cut polygons together;
            # separate surfaces can incorrectly paint the plane over the endcap.
            axis.add_collection3d(Poly3DCollection(np.concatenate(polygons),facecolors=np.concatenate(colors),
                edgecolors='none',linewidths=0,antialiased=False,zsort='average'))
            for edge in [tuple(c[:,0] for c in shape['cut']),tuple(c[:,-1] for c in shape['cut']),
                         tuple(c[0,:] for c in shape['cut']),tuple(c[-1,:] for c in shape['cut'])]:
                axis.plot(*(c*100 for c in edge),color='#52606d',lw=.7,alpha=.9)
            axis.set(xlim=(-12.5,12.5),ylim=(-2.1,2.1),zlim=(-2.1,2.1),
                xlabel='轴向 z / cm',ylabel='x / cm',zlabel='y / cm')
            axis.set_xticks([-10,0,10]); axis.set_yticks([-2,0,2]); axis.set_zticks([-2,0,2])
            axis.set_box_aspect((25,4.2,4.2),zoom=1.12)
            axis.view_init(elev=25,azim=30)
            axis.tick_params(labelsize=7,pad=0)
            axis.set_title(f'Q{dataset["question"]} {"温度" if p == 0 else "含水率"}  '
                f't={dataset["times"][index]/3600:.3f} h\nR={r[-1]*100:.4f} cm',fontsize=10)
    for p in [0,1]:
        limits = config.get('color_limits',[(28,53),(0,2.55)])[p]
        scalar = ScalarMappable(norm=Normalize(*limits),cmap='inferno' if p == 0 else 'viridis')
        fig.colorbar(scalar,ax=axes[p,:].tolist(),shrink=.68,pad=.035,
            label='温度 / ℃' if p == 0 else '干基含水率 C / (kg/kg)')
    fig.suptitle(f'二维轴对称场旋转展开 · 斜切圆柱 · 相对进度 {progress[index]*100:.1f}%\n'
        '同变量共用固定色标；各面板标注实际时间；Q4 按真实半径收缩',fontsize=12)
    return fig
