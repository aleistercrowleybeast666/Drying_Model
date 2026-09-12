"""Portable, runtime-only file-backed cache for the unchanged thermal closures.

The operator and RK4 ASTs are copied verbatim from the original functions.
Only closure storage becomes module constants and cache=True is added. Separate
modules preserve the original operator global binding used by mass instrumentation.
No CPU-specific cache or generated module is included in the distribution.
"""
import ast
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import sys
import textwrap
from functools import lru_cache

import numpy as np


def Judge_LoadWater(spec):
    from .runtime import Runtime_GetRoot
    from .studies.water import Water_LoadTable
    return Water_LoadTable(str(Runtime_GetRoot()/spec['water']['table_path']),spec['water']['table_sha256'])


def Judge_GetThermalKernel(spec):
    grid,hl,lv=Judge_LoadWater(spec)
    return Judge_BuildThermalKernel(spec['mode'],{'q1':1,'q23':3,'q4':4}[spec['case']],
        json.dumps(spec['physics'],sort_keys=True),spec['water']['table_sha256'],
        tuple(grid),tuple(hl),tuple(lv),os.environ['NUMBA_CACHE_DIR'])


@lru_cache(maxsize=12)
def Judge_BuildThermalKernel(mode,model,physics_json,water_hash,grid_tuple,hl_tuple,lv_tuple,cache_directory):
    from .rk4 import Rk4_Advance
    from .materials import Material_Evaluate
    from .studies.thermal import Thermal_BuildKernel
    if mode=='M00':return Rk4_Advance
    physics=json.loads(physics_json)
    operator_tree=ast.parse(textwrap.dedent(inspect.getsource(Thermal_BuildKernel)))
    operator=next(n for n in ast.walk(operator_tree) if isinstance(n,ast.FunctionDef) and n.name=='Operator')
    rk_tree=ast.parse(textwrap.dedent(inspect.getsource(Rk4_Advance.py_func)))
    rk=next(n for n in rk_tree.body if isinstance(n,ast.FunctionDef))
    before=[ast.dump(node,include_attributes=False) for node in operator.body], [ast.dump(node,include_attributes=False) for node in rk.body]
    for definition in [operator,rk]:
        definition.decorator_list=ast.parse('@njit(cache=True)\ndef f():pass').body[0].decorator_list
    after=[ast.dump(node,include_attributes=False) for node in operator.body], [ast.dump(node,include_attributes=False) for node in rk.body]
    if before!=after:raise RuntimeError('JIT_NUMERICAL_AST_CHANGED')
    identity=json.dumps(dict(mode=mode,model=model,physics=physics,water_hash=water_hash,ast=before),sort_keys=True)
    digest=hashlib.sha256(identity.encode()).hexdigest()[:24]
    directory=Path(cache_directory).parent/'jit_sources';directory.mkdir(parents=True,exist_ok=True)
    b0=Material_Evaluate(model,physics['T0_K'],physics['C0'])[0]/(1+physics['C0'])
    constants=dict(b0=float(b0),R0=physics['R0_m'],latent=mode in ['M10','M11'],sensible=mode in ['M01','M11'])
    operator_name='drying_thermal_operator_'+digest;rk_name='drying_thermal_rk4_'+digest
    operator_source=('import numpy as np\nfrom numba import njit\nfrom drying.operators import Operator_Evaluate\n'
        'from drying.studies.thermal import Thermal_AddOperator\n'+
        '\n'.join(name+' = '+repr(value) for name,value in constants.items())+'\n'+
        '\n'.join(name+' = np.array('+repr(list(value))+', dtype=np.float64)' for name,value in
            [('grid',grid_tuple),('hl',hl_tuple),('Lv',lv_tuple)])+'\n'+ast.unparse(operator)+'\n')
    rk_source=('from drying.rk4 import *\nfrom '+operator_name+' import Operator as Operator_Evaluate\n'+ast.unparse(rk)+'\n')
    for name,source in [(operator_name,operator_source),(rk_name,rk_source)]:
        path=directory/(name+'.py')
        if path.exists() and path.read_text(encoding='utf-8')!=source:
            raise RuntimeError('JIT_SOURCE_CACHE_MISMATCH: '+name)
        if not path.exists():
            temporary=path.with_suffix('.tmp');temporary.write_text(source,encoding='utf-8');os.replace(temporary,path)
    if str(directory) not in sys.path:sys.path.insert(0,str(directory))
    compiled=importlib.import_module(rk_name).Rk4_Advance
    def Advance_Guarded(*arguments):
        values=list(arguments);values[14]=grid_tuple[0]+.05;values[15]=grid_tuple[-1]-.05
        return compiled(*values)
    Advance_Guarded.py_func=compiled.py_func
    Advance_Guarded.compiled=compiled
    Advance_Guarded.cache_identity=digest
    return Advance_Guarded


def Judge_InstallRuntimeBindings():
    """Only the judge process uses these I/O/JIT adapters; specs stay unchanged."""
    from .studies import thermal
    thermal.Thermal_GetTable=Judge_LoadWater
    thermal.Thermal_GetKernel=Judge_GetThermalKernel
