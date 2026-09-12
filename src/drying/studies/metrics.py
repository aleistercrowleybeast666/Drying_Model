"""Postprocessing definitions in physical units; no PDE integration in this module."""
import numpy as np


def Metrics_GetFront(r,C,threshold):
    r=np.asarray(r);C=np.asarray(C);wet=C>threshold
    crossings=np.flatnonzero(wet[1:]!=wet[:-1])
    if not np.any(wet):return dict(radius_m=0.,relative_radius=0.,wet_volume_fraction=0.,status='ALL_DRY',crossings=0)
    if np.all(wet):return dict(radius_m=float(r[-1]),relative_radius=1.,wet_volume_fraction=1.,status='ALL_WET',crossings=0)
    edges=[]
    for i in crossings:
        edges.append(float(r[i]+(threshold-C[i])*(r[i+1]-r[i])/(C[i+1]-C[i])))
    radius=max([float(r[-1])] if wet[-1] else []) if wet[-1] else max(edges)
    monotone_core=bool(wet[0] and len(crossings)==1 and np.all(np.diff(C)<=1e-10))
    status='MONOTONE_CORE' if monotone_core else 'MULTIPLE_CROSSINGS' if len(crossings)>1 else 'NON_CORE'
    return dict(radius_m=radius,relative_radius=radius/r[-1],wet_volume_fraction=(radius/r[-1])**2 if monotone_core else None,
        status=status,crossings=len(crossings))


def Metrics_GetTies(r,C,tolerance=1e-9):
    maximum=float(np.max(C));where=np.flatnonzero(np.abs(C-maximum)<=tolerance)
    return dict(maximum=maximum,count=len(where),r_min_m=float(r[where].min()),r_max_m=float(r[where].max()),
        tolerance=tolerance,unique=len(where)==1)


def Metrics_GetDerivative(t,y,stage):
    result=np.full(len(t),np.nan)
    # Each local derivative stays within one grid stage; input-knot slopes remain visible.
    breaks=np.r_[0,np.flatnonzero(np.diff(stage)!=0)+1,len(t)]
    for a,b in zip(breaks[:-1],breaks[1:]):
        if b-a>=3:result[a:b]=np.gradient(y[a:b],t[a:b],edge_order=2)
    return result


def Metrics_GetClock(t,D,R):
    integrand=D/R**2;increments=np.diff(t)*(integrand[:-1]+integrand[1:])/2
    clock=np.r_[0.,np.cumsum(increments)]
    keep=np.unique(np.r_[np.arange(0,len(t),2),len(t)-1]);coarse=np.trapezoid(integrand[keep],t[keep])
    return clock,dict(full=float(clock[-1]),half_sampling=float(coarse),absolute_difference=float(abs(clock[-1]-coarse)),units='dimensionless')


def Metrics_GetDrivers(T,C,R,model):
    a=.45 if model==3 else .30;b=3850.
    thermal=b*(1/T[0]-1/T);moisture=a*(1/C[0]-1/C);radius=2*np.log(R[0]/R)
    direct=(-a/C-b/T)-(-a/C[0]-b/T[0])+2*np.log(R[0]/R)
    error=float(np.max(np.abs(thermal+moisture+radius-direct)))
    return thermal,moisture,radius,error


def Metrics_GetThermalTime(t,Tmin,Tmax,tail_T,tolerance=.2):
    close=(np.abs(Tmin-tail_T)<=tolerance)&(np.abs(Tmax-tail_T)<=tolerance)
    future=np.logical_and.accumulate(close[::-1])[::-1]
    valid=np.flatnonzero(future)
    return float(t[valid[0]]) if len(valid) else None


def Metrics_GetEndEffects(error_T,error_C,volumes,z,half_length=.125):
    result={}
    for key,error,threshold in [('T',error_T,.2),('C',error_C,.003)]:
        affected=np.abs(error)>threshold;axial=np.any(affected,axis=0)
        depths=half_length-np.abs(z)
        depth=float(np.max(depths[axial])) if np.any(axial) else 0.
        result.update({f'depth_{key}_m':depth,f'volume_fraction_{key}':float(np.sum(volumes*affected)/np.sum(volumes)),
            f'middle_affected_{key}':bool(np.any(affected[:,0])),f'max_abs_{key}':float(np.max(np.abs(error)))})
    return result


def Metrics_GetEventSensitivity(t,Cmax,ties_min,ties_max,event,error_C):
    if not event:return dict(status='NOT_APPLICABLE',reason='NOT_DRY_WITHIN_72H',estimated_dt_s=None)
    at=event['raw_event_s'];slopes=[]
    for width in [600.,1800.]:
        keep=(t>=at-width)&(t<=at+width)
        if keep.sum()<5:return dict(status='NOT_APPLICABLE',reason='insufficient event neighborhood',estimated_dt_s=None)
        if np.max(ties_max[keep]-ties_min[keep])>1e-6 or np.ptp(ties_min[keep])>1e-6:
            return dict(status='NOT_APPLICABLE',reason='controlling region not unique/stable',estimated_dt_s=None)
        if np.any(np.diff(Cmax[keep])>=0):return dict(status='NOT_APPLICABLE',reason='nonmonotone neighborhood',estimated_dt_s=None)
        slopes.append(float(np.polyfit(t[keep]-at,Cmax[keep],1)[0]))
    ratio=abs(slopes[0]-slopes[1])/max(abs(slopes[0]),1e-30)
    if ratio>.1 or abs(slopes[0])<1e-12:return dict(status='NOT_APPLICABLE',reason='flat or window-sensitive slope',estimated_dt_s=None)
    return dict(status='APPLICABLE',reason='local first-order estimate, not confidence interval',slope_600_s=slopes[0],
        slope_1800_s=slopes[1],relative_window_difference=ratio,estimated_dt_s=float(abs(error_C/slopes[0])))


def Metrics_GetStages(t,rate,rule,end_s=None):
    """Classify observed rate shape; medians diagnose trends, never alter states."""
    if not 0<rule['endpoint_window_fraction']<.5 or not 0<rule['minimum_peak_contrast_fraction']<1 or rule['minimum_samples']<3:
        raise ValueError('INVALID_STAGE_IDENTIFICATION_RULE')
    keep=np.isfinite(rate)&(t<=end_s if end_s is not None else True)
    t=np.asarray(t)[keep];rate=np.asarray(rate)[keep]
    if len(t)<rule['minimum_samples']:
        return dict(stage_status='INSUFFICIENT_SAMPLES',three_stage=False)
    peak=int(np.argmax(rate));fraction=rule['endpoint_window_fraction']
    # Windows belong to each side of the observed peak. A long slow tail must
    # not erase a short, well-resolved rising limb by moving its window past it.
    initial_window=fraction*(t[peak]-t[0]);final_window=fraction*(t[-1]-t[peak])
    first=float(np.median(rate[t<=t[0]+initial_window]));last=float(np.median(rate[t>=t[-1]-final_window]))
    maximum=float(rate[peak]);contrast=rule['minimum_peak_contrast_fraction']*max(abs(maximum),1e-30)
    rise=maximum-first>contrast and peak>=2
    fall=maximum-last>contrast and len(t)-peak>=3
    label='SLOW_FAST_SLOW' if rise and fall else 'NO_THREE_STAGE_PATTERN'
    return dict(stage_status=label,three_stage=bool(rise and fall),peak_time_s=float(t[peak]),
        peak_rate_kg_kg_s=maximum,initial_median_rate_kg_kg_s=first,final_median_rate_kg_kg_s=last,
        rising_limb_identified=bool(rise),falling_limb_identified=bool(fall),observation_end_s=float(t[-1]),
        initial_rate_window_end_s=float(t[0]+initial_window),final_rate_window_start_s=float(t[-1]-final_window))
