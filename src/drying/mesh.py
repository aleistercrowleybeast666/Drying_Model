"""Frozen, pilot-gradient driven tensor-product finite-volume meshes."""
import hashlib
import json
from enum import IntEnum
from pathlib import Path
import numpy as np
from .storage import Storage_WriteArray, Storage_WriteJson, Storage_HashFiles


class MeshCheckResult(IntEnum):
    VALID = 0
    MESH_NON_MONOTONIC = 1
    MESH_CELL_TOO_SMALL = 2
    MESH_NEIGHBOR_RATIO_EXCEEDED = 3
    MESH_MONITOR_INVALID = 4
    MESH_CELL_TOO_LARGE = 5


def Mesh_BuildUniform(count):
    return np.linspace(0., 1., count+1)


def Mesh_Check(faces, cfg):
    widths = np.diff(faces)
    if not np.isfinite(faces).all() or faces[0] != 0 or faces[-1] != 1 or np.any(widths <= 0):
        return MeshCheckResult.MESH_NON_MONOTONIC
    if widths.min()*len(widths) < cfg['min_width_fraction']-1e-10:
        return MeshCheckResult.MESH_CELL_TOO_SMALL
    if widths.max()*len(widths) > cfg['max_width_fraction']+1e-10:
        return MeshCheckResult.MESH_CELL_TOO_LARGE
    if len(widths) > 1 and max(np.max(widths[1:]/widths[:-1]), np.max(widths[:-1]/widths[1:])) > cfg['max_neighbor_cell_ratio']+1e-10:
        return MeshCheckResult.MESH_NEIGHBOR_RATIO_EXCEEDED
    return MeshCheckResult.VALID


def Mesh_Equidistribute(x, monitor, count):
    if not np.isfinite(monitor).all() or np.any(monitor <= 0) or np.any(np.diff(x) <= 0):
        raise ValueError('MESH_MONITOR_INVALID: positive continuous monitor required')
    cumulative = np.r_[0., np.cumsum(np.diff(x)*(monitor[1:]+monitor[:-1])/2)]
    faces = np.interp(np.linspace(0., cumulative[-1], count+1), cumulative, x)
    faces[0], faces[-1] = 0., 1.
    return faces, cumulative


def Mesh_GetHash(*arrays):
    digest = hashlib.sha256()
    for array in arrays:
        value = np.ascontiguousarray(array, dtype=np.float64)
        digest.update(str(value.shape).encode()); digest.update(value.tobytes())
    return digest.hexdigest()


def Mesh_GetStatistics(faces, scale):
    widths = np.diff(faces)*scale
    return dict(min=float(widths.min()), max=float(widths.max()), mean=float(widths.mean()),
        neighbor_ratio=float(max(np.max(widths[1:]/widths[:-1]), np.max(widths[:-1]/widths[1:]))) if len(widths)>1 else 1.)


def Mesh_GetPilot(root, case, axis):
    """Legacy fields are authorized ONLY as pilot/reference data, never as a new solve."""
    from .cases import Case_LoadConfig, Case_Solve
    root = Path(root); cfg = Case_LoadConfig(root)['mesh']; dim = 1 if axis == 'radial' else 2
    legacy_id = f'{case}_{dim}d_nr{cfg["pilot_nr"]}_nz{1 if dim == 1 else cfg["pilot_nz"]}_dt0.25'
    baseline_path = root/'work/validation/uniform_reference/baseline.json'
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
        legacy = baseline.get('cases', {}).get(legacy_id)
        if legacy and (root/'work/cache'/legacy_id/'status.json').exists():
            saved = json.loads((root/'work/cache'/legacy_id/'status.json').read_text(encoding='utf-8'))
            current_input = json.loads((root/'data/input_manifest.json').read_text(encoding='utf-8'))['hash']
            # Physics inputs/materials remain byte-identical; changed operators cannot relabel the old cache.
            for name in ['materials.py', 'boundaries.py', 'inputs.py']:
                if (root/'src/drying'/name).read_bytes() != (baseline_path.parent/name).read_bytes():
                    raise RuntimeError('CACHE_MISMATCH: legacy pilot physics changed')
            if saved['fingerprint'] != legacy['fingerprint'] or current_input != saved['input_hash'] or not saved['complete']:
                raise RuntimeError('CACHE_MISMATCH: legacy pilot provenance')
            return saved, True
    status = Case_Solve(root, case, dim, nr=cfg['pilot_nr'], nz=cfg['pilot_nz'], tag='pilot',
                        cap=1800 if dim == 2 or case == 'q1' else 259200, mesh_mode='uniform')
    return status, False


def Mesh_BuildMonitor(root, case, axis):
    from .cases import Case_LoadConfig, Case_LoadInputs
    from .sampling import Sampling_GetNodes
    root = Path(root); cfg = Case_LoadConfig(root)['mesh']; inputs = Case_LoadInputs(root)
    status, reused = Mesh_GetPilot(root, case, axis)
    model = dict(q1=1, q23=3, q4=4)[case]
    cap = 1800 if axis == 'axial' or case == 'q1' else 259200
    maximum_gradient = None; lower = np.full(2, np.inf); upper = np.full(2, -np.inf)
    sample_count = 0; min_radius = .02
    for path in sorted((root/'work/cache'/status['case_id']).glob('chunk_*.npz')):
        with np.load(path) as block:
            if str(block['fingerprint']) != status['fingerprint']:
                raise RuntimeError('CACHE_MISMATCH: pilot field')
            times = block['time_s']
            if times[0] > cap:
                break
            fields = block['fields']
        for t, field in zip(times, fields):
            if t > cap:
                break
            r, z, nodes = Sampling_GetNodes(field, float(t), model, inputs)
            x = r/r[-1] if axis == 'radial' else z/z[-1]
            derivative = np.abs(np.gradient(nodes, x, axis=1 if axis == 'radial' else 2, edge_order=2))
            envelope = derivative.max(axis=2 if axis == 'radial' else 1)
            maximum_gradient = envelope if maximum_gradient is None else np.maximum(maximum_gradient, envelope)
            lower = np.minimum(lower, nodes.min(axis=(1,2))); upper = np.maximum(upper, nodes.max(axis=(1,2)))
            min_radius = min(min_radius, float(r[-1])); sample_count += 1
    if sample_count < 2 or maximum_gradient is None:
        raise RuntimeError('MESH_MONITOR_INVALID: pilot has insufficient samples')
    ranges = np.maximum(upper-lower, np.finfo(float).eps)
    gradients = maximum_gradient/ranges[:, None]
    monitor = 1+np.sqrt((cfg['temperature_weight']*gradients[0])**2+(cfg['moisture_weight']*gradients[1])**2)
    for _ in range(cfg['monitor_smoothing_passes']):
        monitor = np.convolve(np.pad(monitor, (1,1), mode='edge'), [.25,.5,.25], mode='valid')
    monitor = np.minimum(monitor, monitor.min()*cfg['max_density_ratio'])
    monitor /= monitor.min()
    dense_x = np.linspace(0., 1., cfg['monitor_points'])
    dense_monitor = np.interp(dense_x, x, monitor)
    return dict(x=dense_x, raw_monitor=dense_monitor, gradients=np.array([np.interp(dense_x,x,g) for g in gradients]),
        metadata=dict(case=case, axis=axis, pilot_id=status['case_id'], pilot_fingerprint=status['fingerprint'],
            pilot_reused=reused, pilot_time_range_s=[0., cap], sample_count=sample_count,
            reference_ranges=ranges.tolist(), minima=lower.tolist(), maxima=upper.tolist(), min_radius=min_radius,
            formula='1 + sqrt((wT max_t |dT/dx| / range(T))^2 + (wC max_t |dC/dx| / range(C))^2)',
            smoothing_passes=cfg['monitor_smoothing_passes'], max_density_ratio=cfg['max_density_ratio']))


def Mesh_GetStabilityBound(root, case, xi, eta, radial_metadata):
    """Conservative row bound over the pilot T/C envelope and minimum radius."""
    from .cases import Case_LoadConfig
    from .materials import Material_Evaluate
    from .operators import Operator_Evaluate
    model = dict(q1=1,q23=3,q4=4)[case]
    samples = np.linspace(radial_metadata['minima'][1], radial_metadata['maxima'][1], 2048)
    properties = np.array([Material_Evaluate(model, radial_metadata['maxima'][0], c) for c in samples])
    capacity = properties[:,0]*properties[:,1]
    alpha, diffusion = np.max(properties[:,2]/capacity), properties[:,3].max()
    state = np.empty((2,len(xi)-1,len(eta)-1)); state[0] = 301.15; state[1] = 2.55
    derivative = np.empty_like(state); rows = np.empty_like(state); props = np.empty((4,*state.shape[1:]))
    largest, code, i, j = Operator_Evaluate(state,radial_metadata['min_radius'],301.15,2.55,model,
        25./capacity.min(),8e-7,len(eta)>2,derivative,props,rows,np.array([1.,1.,alpha,diffusion]),xi,eta)
    if code:
        raise RuntimeError(f'MESH_MONITOR_INVALID: stability evaluation at {i},{j}')
    index = np.unravel_index(rows.argmax(),rows.shape)
    bound = Case_LoadConfig(root)['numerics']['safety']*2.7852935634/(2*largest)
    return float(bound), list(map(int,index))


def Mesh_PrepareCase(root, case):
    from .cases import Case_LoadConfig
    from .diagnostics import Diagnostics_Record
    root = Path(root); config = Case_LoadConfig(root); cfg = config['mesh']
    folder = root/'work/validation/mesh_profiles'; folder.mkdir(parents=True,exist_ok=True)
    signature = hashlib.sha256(json.dumps(dict(mesh=cfg,dt=config['numerics']['dt_s'],safety=config['numerics']['safety'],
        input_hash=json.loads((root/'data/input_manifest.json').read_text(encoding='utf-8'))['hash']),sort_keys=True).encode()).hexdigest()
    summary_path = folder/f'{case}_mesh.json'
    if summary_path.exists():
        saved = json.loads(summary_path.read_text(encoding='utf-8'))
        if saved['configuration_hash'] == signature and all((folder/f'{case}_{axis}_monitor.npz').exists() for axis in ['radial','axial']):
            return saved
    radial, axial = Mesh_BuildMonitor(root,case,'radial'), Mesh_BuildMonitor(root,case,'axial')
    strength = 1.; checks = []
    # Freeze ONE continuous function for all resolutions. Stable coarsest 2D grid
    # controls concentration; impossible fine-grid dt is reported, not concealed.
    while True:
        monitors = [1+strength*(profile['raw_monitor']-1) for profile in [radial,axial]]
        checks = [Mesh_Check(Mesh_Equidistribute(profile['x'],monitor,n)[0],cfg)
            for profile,monitor,counts in [(radial,monitors[0],[cfg['base_nr'],cfg['refined_nr'],cfg['verification_nr']]),
                                           (axial,monitors[1],[cfg['base_nz'],cfg['refined_nz']])]
            for n in counts]
        xi = Mesh_Equidistribute(radial['x'],monitors[0],cfg['base_nr'])[0]
        eta = Mesh_Equidistribute(axial['x'],monitors[1],cfg['base_nz'])[0]
        bound, location = Mesh_GetStabilityBound(root,case,xi,eta,radial['metadata'])
        if all(code == MeshCheckResult.VALID for code in checks) and bound >= config['numerics']['dt_s']*cfg['stability_margin']:
            break
        if strength <= cfg['minimum_monitor_strength']:
            raise RuntimeError(f'ADAPTIVE_MESH_DT_CONFLICT: even weak base mesh bound={bound:g} s')
        strength *= .5
    result = dict(configuration_hash=signature,case=case,monitor_strength=strength,
                  base_stability_bound_s=bound,profiles={},stability=[])
    for profile,monitor,axis,counts in [(radial,monitors[0],'radial',[40,80,160]), (axial,monitors[1],'axial',[125,250])]:
        cumulative = Mesh_Equidistribute(profile['x'],monitor,counts[0])[1]
        digest = Mesh_GetHash(profile['x'],monitor)
        metadata = dict(profile['metadata'],monitor_hash=digest,monitor_strength=strength,
                        monitor_min=float(monitor.min()),monitor_max=float(monitor.max()))
        Storage_WriteArray(folder/f'{case}_{axis}_monitor.npz',x=profile['x'],monitor=monitor,
            raw_monitor=profile['raw_monitor'],gradients=profile['gradients'],cumulative_monitor=cumulative,
            metadata=json.dumps(metadata))
        result['profiles'][axis] = metadata
        for n in counts:
            faces = Mesh_Equidistribute(profile['x'],monitor,n)[0]
            scale = profile['metadata']['min_radius'] if axis=='radial' else .125
            Storage_WriteArray(folder/f'{case}_{axis}_{n}.npz',faces=faces,centers=(faces[:-1]+faces[1:])/2,
                cell_widths=np.diff(faces),monitor=monitor,cumulative_monitor=cumulative,
                monitor_hash=digest,statistics=json.dumps(Mesh_GetStatistics(faces,scale)))
    for nr,nz in [(40,1),(80,1),(160,1),(40,125),(80,125),(40,250)]:
        xi = Mesh_Equidistribute(radial['x'],monitors[0],nr)[0]
        eta = Mesh_BuildUniform(1) if nz==1 else Mesh_Equidistribute(axial['x'],monitors[1],nz)[0]
        bound, location = Mesh_GetStabilityBound(root,case,xi,eta,radial['metadata'])
        uniform_bound,_ = Mesh_GetStabilityBound(root,case,Mesh_BuildUniform(nr),Mesh_BuildUniform(nz),radial['metadata'])
        check = dict(case=case,dimension=1 if nz==1 else 2,nr=nr,nz=nz,requested_dt=config['numerics']['dt_s'],
            stability_bound=bound,uniform_stability_bound=uniform_bound,failing_location=location,
            dt_compatible=bound>=config['numerics']['dt_s'],min_max_dr=Mesh_GetStatistics(xi,radial['metadata']['min_radius']),
            min_max_dz=Mesh_GetStatistics(eta,.125),monitor_min=min(float(m.min()) for m in monitors),
            monitor_max=max(float(m.max()) for m in monitors))
        result['stability'].append(check)
        if not check['dt_compatible']:
            Diagnostics_Record(root,'ADAPTIVE_MESH_DT_CONFLICT','WARNING',**check,
                reason='Fine grid cannot guarantee 0.25 s, even before strong clustering; requested dt stays fixed and existing RK4 safety limiter remains active.')
    Storage_WriteJson(summary_path,result)
    return result


def Mesh_BuildAdaptive(root,case,nr,nz,mode):
    if mode == 'uniform':
        xi,eta = Mesh_BuildUniform(nr),Mesh_BuildUniform(nz)
        metadata = dict(mesh_mode=mode,radial_monitor_hash=None,axial_monitor_hash=None)
    else:
        summary = Mesh_PrepareCase(root,case)
        folder = Path(root)/'work/validation/mesh_profiles'
        faces = []
        for axis,count in [('radial',nr),('axial',nz)]:
            with np.load(folder/f'{case}_{axis}_monitor.npz') as saved:
                faces.append(Mesh_Equidistribute(saved['x'],saved['monitor'],count)[0])
        xi,eta = faces
        metadata = dict(mesh_mode=mode,radial_monitor_hash=summary['profiles']['radial']['monitor_hash'],
                        axial_monitor_hash=summary['profiles']['axial']['monitor_hash'] if nz>1 else None)
    metadata.update(mesh_profile_hash=Mesh_GetHash(xi,eta),nr=nr,nz=nz,
        radial_initial=Mesh_GetStatistics(xi,.02),radial_minimum=Mesh_GetStatistics(xi,.01198 if case=='q4' else .02),
        axial=Mesh_GetStatistics(eta,.125))
    return (xi,eta),metadata


def Mesh_PlotProfiles(root):
    from .plots import Plot_SetStyle
    import matplotlib.pyplot as plt
    Plot_SetStyle(); root=Path(root); folder=root/'work/validation/mesh_profiles'
    fig,axes=plt.subplots(3,4,figsize=(15,9),layout='constrained')
    for row,case in enumerate(['q1','q23','q4']):
        summary=Mesh_PrepareCase(root,case)
        with np.load(folder/f'{case}_radial_monitor.npz') as data:
            axes[row,0].plot(data['x'],data['monitor']);axes[row,0].set(title=f'{case} 径向监测函数',xlabel='ξ',ylabel='M')
        for n in [40,80,160]:
            with np.load(folder/f'{case}_radial_{n}.npz') as data:
                axes[row,1].plot(data['faces'],np.full(n+1,n),'|',label=str(n))
                axes[row,2].plot(data['centers'],data['cell_widths']*.02*1000,label=str(n))
        axes[row,1].set(title='归一化径向网格',xlabel='ξ',ylabel='N')
        axes[row,2].set(title='初始径向单元宽度',xlabel='ξ',ylabel='Δr / mm');axes[row,2].legend()
        for n in [125,250]:
            with np.load(folder/f'{case}_axial_{n}.npz') as data:
                axes[row,3].plot(data['centers'],data['cell_widths']*.125*1000,label=str(n))
        axes[row,3].set(title='轴向单元宽度',xlabel='η',ylabel='Δz / mm');axes[row,3].legend()
    fig.savefig(folder/'mesh_profiles.png');plt.close(fig)
