"""Read-only instrumentation of the exact production FV operator and RK4 AST.

The additional accumulator is never read by a physical state update. Boundary
flux is captured from the actual FV boundary subtraction, including its sign.
Rejected trials overwrite the four stage slots and never enter the integral.
"""
import ast
import copy
import inspect
import textwrap
import types
import numpy as np
from numba import njit
from ..operators import Operator_Evaluate
from ..rk4 import Rk4_Advance


@njit(cache=True)
def MassBalance_GetWeightedMass(state, weights):
    total = 0.; correction = 0.
    for i in range(state.shape[1]):
        for j in range(state.shape[2]):
            value = state[1, i, j]*weights[i, j]-correction
            updated = total+value
            correction = (updated-total)-value
            total = updated
    return total


@njit(cache=True)
def MassBalance_Accumulate(audit, weights, state, flows, dt, time_s, radius):
    increment = dt/6*(flows[0]+2*flows[1]+2*flows[2]+flows[3])
    value = increment-audit[2]
    updated = audit[1]+value
    audit[2] = (updated-audit[1])-value
    audit[1] = updated
    audit[3] += dt/6*(abs(flows[0])+2*abs(flows[1])+2*abs(flows[2])+abs(flows[3]))
    audit[8] += 1
    audit[9] = MassBalance_GetWeightedMass(state, weights)
    audit[10] = (audit[9]-audit[0])+audit[1]
    audit[17] = time_s
    if abs(audit[10]) > audit[4]:
        audit[4] = abs(audit[10]); audit[5] = audit[10]; audit[6] = time_s
        audit[7] = audit[19]; audit[11] = dt
        audit[12:16] = flows; audit[16] = radius
    audit[18] = max(audit[18], audit[9])


def MassBalance_GetFunctionTree(function):
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    definition = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
    definition.decorator_list = []
    return tree, definition


def MassBalance_BuildOperator():
    original = Operator_Evaluate.py_func
    tree, definition = MassBalance_GetFunctionTree(original)
    captures = 0

    class Instrument(ast.NodeTransformer):
        def visit_AugAssign(self, node):
            nonlocal captures
            # These two exact boundary writes are shared by every thermal mode.
            target = ast.unparse(node.target)
            if isinstance(node.op, ast.Sub) and target in ('out[field, nr - 1, j]', 'out[field, i, nz - 1]'):
                captures += 1
                capture = ast.parse('if field == 1:\n    constant[4] += 0.').body[0]
                capture.body[0].value = copy.deepcopy(node.value)
                return [node, capture]
            return node

    tree = Instrument().visit(tree)
    if captures != 2:
        raise RuntimeError('MASS_INSTRUMENTATION_FAILED: original boundary write anchors changed')
    definition.body.insert(0, ast.parse('constant[4] = 0.').body[0])
    namespace = dict(original.__globals__)
    exec(compile(ast.fix_missing_locations(tree), '<mass_boundary_capture>', 'exec'), namespace)
    return njit(namespace[definition.name])


def MassBalance_BuildKernel(spec, b0):
    operator = MassBalance_BuildOperator()
    original = Rk4_Advance.py_func
    if spec['mode'] != 'M00':
        from .thermal import Thermal_GetKernel
        thermal = Thermal_GetKernel(spec).py_func.__globals__['Operator_Evaluate']
        namespace = dict(thermal.py_func.__globals__)
        namespace['Operator_Evaluate'] = operator
        operator = njit(types.FunctionType(thermal.py_func.__code__, namespace,
            thermal.py_func.__name__, thermal.py_func.__defaults__, thermal.py_func.__closure__))
    tree, definition = MassBalance_GetFunctionTree(original)
    for name in ['mass_audit', 'mass_weights']:
        definition.args.args.append(ast.arg(arg=name))
        definition.args.defaults.append(ast.Constant(value=None))
    counts = dict(constant=0, stage=0, accept=0)

    class Instrument(ast.NodeTransformer):
        def visit_Assign(self, node):
            target = ast.unparse(node.targets[0])
            if target == 'constant':
                if ast.unparse(node.value) != 'np.zeros(4)':
                    raise RuntimeError('MASS_INSTRUMENTATION_FAILED: constant storage changed')
                counts['constant'] += 1
                return ast.parse('constant = np.zeros(5)\nmass_stage = np.empty(4)').body
            if isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == 'Operator_Evaluate':
                counts['stage'] += 1
                return [node, *ast.parse('mass_stage[stage] = constant[4]*(mass_b0*(mass_R0/R)**2)*(4*np.pi)').body]
            if target == 'state[:]' and ast.unparse(node.value) == 'trial':
                counts['accept'] += 1
                return [*ast.parse('MassBalance_Accumulate(mass_audit, mass_weights, trial, mass_stage, dt, t+dt, R)').body, node]
            return node

    tree = Instrument().visit(tree)
    if counts != dict(constant=1, stage=1, accept=1):
        raise RuntimeError('MASS_INSTRUMENTATION_FAILED: original RK4 anchors changed '+str(counts))
    namespace = dict(original.__globals__)
    namespace.update(Operator_Evaluate=operator, MassBalance_Accumulate=MassBalance_Accumulate,
        mass_b0=b0, mass_R0=spec['physics']['R0_m'])
    exec(compile(ast.fix_missing_locations(tree), '<mass_RK4_capture>', 'exec'), namespace)
    return njit(namespace[definition.name])
