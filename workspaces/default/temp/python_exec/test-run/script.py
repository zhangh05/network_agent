# Auto-generated sandbox preamble
import sys
import builtins
# Restrict dangerous builtins
for _name in ('eval', 'exec', 'compile', '__import__', 'open', 'input'):
    try: setattr(builtins, _name, None)
    except: pass
# Remove dangerous modules from cached imports
for _mod in list(sys.modules.keys()):
    _top = _mod.split('.')[0]
    if _top in ('os', 'subprocess', 'socket', 'requests', 'urllib',
                'shutil', 'pathlib', 'ctypes', 'multiprocessing', 'threading'):
        sys.modules.pop(_mod, None)
_ = None

print('hello world')