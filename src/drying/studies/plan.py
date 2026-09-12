"""Compute-side output plans, independent of PDE fingerprints and plot style."""
import numpy as np


def Plan_GetFrameTimes(datasets,frames=200):
    common=None
    for data in datasets.values():common=data['time_s'] if common is None else np.intersect1d(common,data['time_s'])
    if common is None or len(common)<frames:raise RuntimeError('STUDY_REFERENCE_INCOMPLETE: common physical frame calendar')
    end=min(259200.,common[-1]);early=round(.6*frames)
    targets=np.r_[np.linspace(0,.06*end,early,endpoint=False),np.linspace(.06*end,end,frames-early)]
    times=common[np.clip(np.searchsorted(common,targets),0,len(common)-1)]
    if np.any(np.diff(times)<=0):raise RuntimeError('STUDY_REFERENCE_INCOMPLETE: duplicate frame timestamps')
    return times


def Plan_Build(manifest,series):
    datasets={};sources={};missing=[]
    for case in ['q23','q4']:
        for mode in ['M00','M10','M01','M11']:
            key=manifest['baseline_keys'][case] if mode=='M00' else next((k for k,v in manifest['series'].items() if v['case']==case and v['mode']==mode and v['kind']=='production'),None)
            if key:datasets[(case,mode)]=series[key];sources[case+'/'+mode]=key
            else:missing.append(case+'/'+mode)
    ready=all(sum(k[0]==c for k in datasets)>=2 for c in ['q23','q4'])
    plan=dict(status='READY' if ready else 'STUDY_REFERENCE_INCOMPLETE',sources=sources,missing=missing,
        panel_order=[['q23/'+m for m in ['M00','M10','M01','M11']],['q4/'+m for m in ['M00','M10','M01','M11']]],
        size_px=[1800,900],frame_count=200,frame_duration_s=.1,early_fraction=.06,early_frames=120,
        fixed_coordinate_limits_cm=[-2.1,2.1],moisture_limits=[0.,2.55],
        temperature_colormap='inferno',moisture_colormap='viridis',
        mapping='actual 1D radial field via r=sqrt(x²+y²); true Q4 R(t); not a 2D PDE solution',
        outputs=['results/studies/animations/thermal_temperature.gif','results/studies/animations/thermal_moisture.gif'])
    if ready:
        times=Plan_GetFrameTimes(datasets)
        plan.update(frame_times_s=times.tolist(),common_time_range_s=[float(times[0]),float(times[-1])],
            temperature_limits_C=[float(min(d['Tmin_K'].min()-273.15 for d in datasets.values())),float(max(d['Tmax_K'].max()-273.15 for d in datasets.values()))])
    manifest['animation_plan']=plan
    names=['end_effect_extent','drying_fronts','drying_kinetics','diffusion_clock_drivers','geometry_control','environment_robustness','thermal_modes','thermal_interactions','verification_evidence']
    requirements={
        'end_effect_extent':len(manifest['end_effects'])>=4,
        'geometry_control':any(v['kind']=='fixed_radius' for v in manifest.get('counterfactuals',[])),
        'environment_robustness':sum(v['kind']=='tail' for v in manifest.get('counterfactuals',[]))==4,
        'thermal_modes':not missing,'thermal_interactions':len(manifest.get('interactions',[]))==2,
        'verification_evidence':sum(c['mode']=='M00' for c in manifest['checks'])==3}
    manifest['figure_plan']=[dict(name=name,path=f'results/studies/figures/{i:02d}_{name}.png',
        status='READY' if requirements.get(name,True) else 'STUDY_REFERENCE_INCOMPLETE',
        source='sealed scientific arrays; 2D PARTIAL only for end effects; other panels use 1D trajectories') for i,name in enumerate(names,1)]
