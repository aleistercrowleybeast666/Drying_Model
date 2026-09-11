import math
import numpy as np
from .sampling import Sampling_GetNodes


def Event_Locate(left, right, left_state, advance, model, inputs, threshold=0.15):
    def Maximum(state, t):
        return float(Sampling_GetNodes(state, t, model, inputs)[2][1].max())
    original_left = left
    original_state = left_state.copy()
    if Maximum(left_state, left) < threshold:
        raise RuntimeError('EVENT_BRACKET_FAILED: left already dry')
    right_state = advance(original_state, original_left, right)[0]
    if Maximum(right_state, right) >= threshold:
        raise RuntimeError('EVENT_BRACKET_FAILED: reconstructed right not strictly dry')
    while right-left > 0.1:
        middle = (left+right)/2
        trial = advance(original_state, original_left, middle)[0]
        if Maximum(trial, middle) < threshold:
            right, right_state = middle, trial
        else:
            left = middle
    report = math.ceil(right/0.36-1e-12)*0.36
    if report > 259200:
        report = right
    report_state = advance(original_state, original_left, report)[0]
    maximum = Maximum(report_state, report)
    if maximum >= threshold:
        raise RuntimeError('EVENT_BRACKET_FAILED: reporting state not dry')
    return dict(left_s=left, right_s=right, width_s=right-left,
                raw_event_s=right, report_s=report, report_h=report/3600,
                left_max_C=Maximum(advance(original_state, original_left, left)[0], left),
                right_max_C=Maximum(right_state, right), report_max_C=maximum), report_state
