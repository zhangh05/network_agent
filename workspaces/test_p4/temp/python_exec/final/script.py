# Auto-generated sandbox preamble — best-effort local sandbox, not container isolation
import sys
import builtins
# v2.0 Final: only disable eval/exec/compile (imports blocked by AST check)
for _name in ('eval', 'exec', 'compile'):
    try: setattr(builtins, _name, None)
    except: pass
# Whittle down cached dangerous modules (already blocked by AST, belt+suspenders)
for _mod in list(sys.modules.keys()):
    _top = _mod.split('.')[0]
    if _top in ('os', 'subprocess', 'socket', 'requests', 'urllib',
                'shutil', 'pathlib', 'ctypes', 'multiprocessing', 'threading'):
        sys.modules.pop(_mod, None)
_ = None

import json; print(json.dumps({"a":1}))