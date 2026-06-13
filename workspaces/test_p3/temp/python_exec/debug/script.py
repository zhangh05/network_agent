# Auto-generated sandbox preamble
import sys
import os
# Restrict dangerous builtins
for _name in ('eval', 'exec', 'compile', '__import__', 'open', 'input'):
    if _name in __builtins__:
        __builtins__[_name] = None
# Remove dangerous modules from cached imports
for _mod in list(sys.modules.keys()):
    _top = _mod.split('.')[0]
    if _top in ('os', 'subprocess', 'socket', 'requests', 'urllib',
                'shutil', 'pathlib', 'ctypes', 'multiprocessing', 'threading'):
        sys.modules.pop(_mod, None)
_ = None

print(42)