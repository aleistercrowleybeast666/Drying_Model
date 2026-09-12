"""Volume-weighted response clocks; derivatives never modify stored PDE states."""
from pathlib import Path
import numpy as np
from ..geometry import Geometry_GetCells
from ..inputs import Input_AtTime
from ..storage import Storage_WriteArray, Storage_WriteJson
from .baseline import Baseline_HashFile, Baseline_ReadJson
from .trajectory import Trajectory_Iter, Trajectory_IterBaseline, Trajectory_GetInputs
from .analysis import Analysis_GetExactState, Analysis_LoadSeries
from .metrics import Metrics_GetDerivative


def Kinetics_GetVolumeMeans(state, mesh, radius):
    _, _, volumes = Geometry_GetCells(state.shape[1], state.shape[2], radius, mesh=mesh)
    return np.sum(state*volumes[None, :, :], axis=(1, 2))/np.sum(volumes)


def Kinetics_GetHalfResponse(time, values, initial, final, descending=False):
    change = initial-final if descending else final-initial
    if change <= 1e-12:
        return dict(status='NOT_APPLICABLE', time_s=None, bracket_s=None, reason='zero or nonpositive net response')
    response = (initial-values)/change if descending else (values-initial)/change
    indices = np.flatnonzero(response >= .5)
    if not len(indices):
        return dict(status='NOT_REACHED', time_s=None, bracket_s=None)
    i = int(indices[0])
    if i == 0:
        crossing = float(time[0]);bracket = [crossing, crossing]
    else:
        crossing = float(time[i-1]+(.5-response[i-1])*(time[i]-time[i-1])/(response[i]-response[i-1]))
        bracket = [float(time[i-1]), float(time[i])]
    return dict(status='REACHED', time_s=crossing, bracket_s=bracket,
                method='earliest crossing; piecewise linear interpolation of saved volume averages, not drying-event localization')


def Kinetics_GetRadiusPeaks(radius_input, end_s):
    starts = radius_input[:-1, 0]
    ends = np.minimum(radius_input[1:, 0], end_s)
    rates = -np.diff(radius_input[:, 1])/np.diff(radius_input[:, 0])
    valid = (starts < end_s) & (ends > starts)
    maximum = float(np.max(rates[valid]))
    chosen = np.flatnonzero(valid & np.isclose(rates, maximum, rtol=1e-12, atol=1e-15))
    intervals = []
    for i in chosen:
        if intervals and abs(intervals[-1][1]-starts[i]) < 1e-8:
            intervals[-1][1] = float(ends[i])
        else:
            intervals.append([float(starts[i]), float(ends[i])])
    return maximum, intervals


def Kinetics_GetTiming(time, Tmean, Cmean, R, vT, vC, rate_valid, radius_input, end_s, source_id):
    keep = time <= end_s+1e-8
    t = time[keep];T = Tmean[keep];C = Cmean[keep];r = R[keep]
    if abs(t[-1]-end_s) > 1e-7:
        raise RuntimeError('KINETICS_ENDPOINT_MISSING: exact formal endpoint required')
    valid = keep & rate_valid & np.isfinite(vT) & np.isfinite(vC)
    indices = np.flatnonzero(valid)
    it = int(indices[np.argmax(vT[valid])]);ic = int(indices[np.argmax(vC[valid])])
    vr, intervals = Kinetics_GetRadiusPeaks(radius_input, end_s)
    T50 = Kinetics_GetHalfResponse(t, T, T[0], T[-1])
    C50 = Kinetics_GetHalfResponse(t, C, C[0], C[-1], True)
    rt = np.unique(np.r_[radius_input[radius_input[:, 0] < end_s, 0], end_s])
    rv = np.interp(rt, radius_input[:, 0], radius_input[:, 1])
    R50 = Kinetics_GetHalfResponse(rt, rv, rv[0], rv[-1], True)
    result = dict(case='q4', mode='M00', source_case_id=source_id, study_id='q4_peak_response_timing',
        time_unit='s', observation_start_s=0., observation_end_s=end_s,
        t_T_peak=float(time[it]), vT_peak=float(vT[it]), vT_unit='K/s',
        t_C_peak=float(time[ic]), vC_peak=float(vC[ic]), vC_unit='(kg/kg)/s',
        T_peak_at_window_boundary=bool(it == indices[0] or it == indices[-1]),
        C_peak_at_window_boundary=bool(ic == indices[0] or ic == indices[-1]),
        R_peak_interval_start=intervals[0][0], R_peak_interval_end=intervals[0][1],
        R_peak_intervals_s=intervals, vR_peak=vr, vR_unit='m/s',
        delta_R_to_T_interval_start_s=float(time[it]-intervals[0][0]),
        delta_R_to_T_interval_end_s=float(time[it]-intervals[0][1]),
        delta_R_to_C_interval_start_s=float(time[ic]-intervals[0][0]),
        delta_R_to_C_interval_end_s=float(time[ic]-intervals[0][1]),
        delta_T_to_C=float(time[ic]-time[it]),
        radius_interval_relations=[dict(start_s=a, end_s=b, delta_R_to_T_s=[float(time[it]-a), float(time[it]-b)],
            delta_R_to_C_s=[float(time[ic]-a), float(time[ic]-b)]) for a, b in intervals],
        t_T50=T50['time_s'], t_C50=C50['time_s'], t_R50=R50['time_s'],
        half_response_details=dict(T=T50, C=C50, R=R50),
        T_initial_K=float(T[0]), T_final_K=float(T[-1]), C_initial=float(C[0]), C_endpoint=float(C[-1]),
        R_initial_m=float(r[0]), R_endpoint_m=float(r[-1]),
        derivative_method='three-point centered differences on canonical saved outputs within each remesh stage; second-order one-sided edges; additional near-duplicate event times excluded',
        derivative_sampling='10 s where saved; Q4 uses its actual 60 s outputs; late outputs 60 s; no invented denser PDE samples',
        smoothing_method='none; regular output selection prevents near-duplicate-time noise',
        lag_convention='target time minus source time; positive means later response; interval endpoint relations are not a phase angle',
        t50_reference='initial to exact frozen Q4 formal drying endpoint for T, C and R')
    for name, a, b in [('delta_R50_to_T50', R50, T50), ('delta_R50_to_C50', R50, C50), ('delta_T50_to_C50', T50, C50)]:
        result[name] = b['time_s']-a['time_s'] if a['time_s'] is not None and b['time_s'] is not None else None
    return result


def Kinetics_Extract(root, manifest, key):
    root = Path(root);spec = manifest['specs'][key];entry = manifest['series'][key]
    data = Analysis_LoadSeries(root, entry);times = data['time_s']
    output = root / 'work/studies/technical/plot_payload' / (key+'_kinetics.npz')
    metadata_path = output.with_suffix('.json')
    signature = dict(source_series_sha256=entry['sha256'], source_code_sha256=Baseline_HashFile(Path(__file__)))
    if output.exists() and metadata_path.exists():
        previous = Baseline_ReadJson(metadata_path)
        if previous['signature'] == signature and previous['sha256'] == Baseline_HashFile(output):
            return previous
    inputs = Trajectory_GetInputs(root, spec)
    source = Trajectory_IterBaseline(root, spec['case']) if entry['baseline'] else Trajectory_Iter(root, key)
    means = {}
    for t, state, mesh in source:
        R = Input_AtTime(t, *inputs, spec['shrink'])[2]
        means[t] = Kinetics_GetVolumeMeans(state, mesh, R)
    for t in times:
        if t not in means:
            state, mesh = Analysis_GetExactState(root, spec, float(t), entry['baseline'])
            means[t] = Kinetics_GetVolumeMeans(state, mesh, Input_AtTime(t, *inputs, spec['shrink'])[2])
    averages = np.array([means[t] for t in times])
    difference = float(np.max(np.abs(averages[:, 1]-data['Cmean'])))
    if difference > 1e-12:
        raise RuntimeError('VOLUME_MEAN_INCONSISTENT: '+key)
    regular = np.isclose(np.mod(times, np.where(times <= 10800., 10., 60.)), 0., atol=1e-8)
    selected = np.flatnonzero(regular)
    derivatives = [Metrics_GetDerivative(times[selected], averages[selected, field], data['stage_nr'][selected]) for field in [0, 1]]
    vt = np.full(len(times), np.nan);vc = vt.copy()
    # Interpolate derivative estimates only; original state averages stay unchanged.
    for stage in np.unique(data['stage_nr']):
        available = selected[(data['stage_nr'][selected] == stage) & np.isfinite(derivatives[0]) & np.isfinite(derivatives[1])]
        if len(available) < 2:continue
        current = data['stage_nr'] == stage
        indices = np.searchsorted(selected, available)
        vt[current] = np.interp(times[current], times[available], derivatives[0][indices])
        vc[current] = -np.interp(times[current], times[available], derivatives[1][indices])
    arrays = dict(time_s=times, T_mean_volume=averages[:, 0], C_mean_volume=averages[:, 1],
        dTmean_dt=vt, minus_dCmean_dt=vc, R=data['radius_m'], minus_dR_dt=-data['radius_rate_m_s'],
        derivative_canonical_sample=regular, stage_nr=data['stage_nr'])
    Storage_WriteArray(output, **arrays)
    metadata = dict(experiment_id=key, case=spec['case'], mode=spec['mode'], path=output.relative_to(root).as_posix(),
        sha256=Baseline_HashFile(output), signature=signature, maximum_Cmean_consistency_difference=difference,
        units=dict(time_s='s', T_mean_volume='K', C_mean_volume='kg/kg', dTmean_dt='K/s',
            minus_dCmean_dt='(kg/kg)/s', R='m', minus_dR_dt='m/s'),
        volume_definition='sum(U_i * actual cylindrical FV volume_i)/sum(volume_i); boundary reconstruction nodes carry no artificial volume',
        arrays={name:dict(shape=list(value.shape), units='categorical' if value.dtype == bool else 'see units') for name, value in arrays.items()})
    if key == manifest['baseline_keys']['q4']:
        metadata['timing'] = Kinetics_GetTiming(times, averages[:, 0], averages[:, 1], data['radius_m'], vt, vc,
            regular, inputs[1], manifest['statuses'][key]['event']['report_s'], key)
    Storage_WriteJson(metadata_path, metadata)
    return metadata
