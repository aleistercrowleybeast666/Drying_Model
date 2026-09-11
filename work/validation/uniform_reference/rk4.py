"""Classical explicit four-stage RK4 with simultaneous T/C stages and rejection."""
from enum import IntEnum
import numpy as np
from numba import njit
from .inputs import Input_AtTime
from .operators import Operator_Evaluate
from .sampling import Sampling_MaxMoisture


class RkStepResult(IntEnum):
    ACCEPTED = 0
    STATE_NONFINITE = 1
    MOISTURE_NONPOSITIVE = 2
    PROPERTY_NONPOSITIVE = 3
    TEMPERATURE_ENVELOPE = 4
    STABILITY_LIMIT = 5
    MIN_DT_REACHED = 6
    MAX_STEPS_REACHED = 7


@njit(cache=True)
def Rk4_Advance(U, t, stop, requested, model, environment, radius, tail,
                shrink, ends, safety, min_dt, max_rejections, max_steps,
                Tmin, Tmax, replay, h=25., hm=8e-7, threshold=0.15):
    state = U.copy()
    stages = np.empty((4,) + U.shape, dtype=np.float64)
    trial = U.copy()
    props = np.empty((4, U.shape[1], U.shape[2]), dtype=np.float64)
    rows = np.empty_like(U)
    constant = np.zeros(4)
    accepted = np.empty(max_steps, dtype=np.float64)
    # Rejection rows: t,dt,rk_stage,code,i,j,T,C,R,Te,He,attempt.
    rejected = np.empty((max_rejections*4+16, 12), dtype=np.float64)
    count, reject_count, limited, replay_index = 0, 0, 0, 0
    event_left, event_right = -1., -1.
    event_state = U.copy()
    min_accepted, max_accepted = np.inf, 0.
    while t < stop-1e-9:
        if count >= max_steps:
            return state, t, accepted[:count], rejected[:reject_count], 7, limited, event_left, event_right, event_state, min_accepted, max_accepted
        # Every interpolation knot is a segment boundary. At 14400, k4 is
        # evaluated on the left; the next step's k1 uses the tail mean.
        segment = min(stop, (np.floor((t+1e-8)/60)+1)*60) if t < 14400-1e-8 else stop
        if shrink:
            segment = min(segment, (np.floor((t+1e-8)/1800)+1)*1800)
        dt = min(requested, segment-t)
        while replay_index < replay.size and replay[replay_index] <= t+1e-9:
            replay_index += 1
        if replay_index < replay.size:
            dt = min(dt, replay[replay_index]-t)
        retries = 0
        while True:
            valid = True
            largest = 0.
            for stage in range(4):
                fraction = 0. if stage == 0 else (1. if stage == 3 else 0.5)
                if stage == 0:
                    trial[:] = state
                else:
                    trial[:] = state + (fraction*dt)*stages[stage-1]
                ts = t+fraction*dt
                Te, He, R = Input_AtTime(ts, environment, radius, tail, shrink, t >= 14400-1e-9)
                largest, code, ii, jj = Operator_Evaluate(trial, R, Te, He, model,
                    h, hm, ends, stages[stage], props, rows, constant)
                if code == 0:
                    for i in range(trial.shape[1]):
                        for j in range(trial.shape[2]):
                            if trial[0, i, j] < Tmin-0.05 or trial[0, i, j] > Tmax+0.05:
                                code, ii, jj = 4, i, j
                bound = safety*2.7852935634/(2*largest) if largest > 0 else 1e100
                if code == 0 and dt > bound*(1+1e-12):
                    code, ii, jj = 5, 0, 0
                    limited += 1
                if code != 0:
                    valid = False
                    break
            if valid:
                trial[:] = state + dt/6*(stages[0]+2*stages[1]+2*stages[2]+stages[3])
                code, ii, jj = 0, 0, 0
                for i in range(trial.shape[1]):
                    for j in range(trial.shape[2]):
                        T, C = trial[0, i, j], trial[1, i, j]
                        if not np.isfinite(T) or not np.isfinite(C):
                            code, ii, jj = 1, i, j
                        elif C <= 0:
                            code, ii, jj = 2, i, j
                        elif T < Tmin-0.05 or T > Tmax+0.05:
                            code, ii, jj = 4, i, j
                valid = code == 0
                stage = 4
            if valid:
                break
            if code != 5:
                if reject_count >= rejected.shape[0]:
                    return state, t, accepted[:count], rejected[:reject_count], code, limited, event_left, event_right, event_state, min_accepted, max_accepted
                rejected[reject_count] = np.array([t, dt, stage+1, code, ii, jj,
                    trial[0, ii, jj], trial[1, ii, jj], R, Te, He, retries+1])
                reject_count += 1
            # Dyadic protection makes step-history replay reproducible.
            dt *= 0.5
            retries += 1
            if dt < min_dt or retries > max_rejections:
                return state, t, accepted[:count], rejected[:reject_count], 6, limited, event_left, event_right, event_state, min_accepted, max_accepted
        if event_left < 0 and model != 1:
            before = Sampling_MaxMoisture(state, He)[0]
            after = Sampling_MaxMoisture(trial, He)[0]
            if before >= threshold and after < threshold:
                event_left, event_right = t, t+dt
                event_state[:] = state
        state[:] = trial
        t += dt
        accepted[count] = t
        count += 1
        min_accepted = min(min_accepted, dt)
        max_accepted = max(max_accepted, dt)
    return state, t, accepted[:count], rejected[:reject_count], 0, limited, event_left, event_right, event_state, min_accepted, max_accepted


def Rk4_ScalarStep(function, t, value, dt):
    k1 = function(t, value)
    k2 = function(t+dt/2, value+dt*k1/2)
    k3 = function(t+dt/2, value+dt*k2/2)
    k4 = function(t+dt, value+dt*k3)
    return value+dt*(k1+2*k2+2*k3+k4)/6
