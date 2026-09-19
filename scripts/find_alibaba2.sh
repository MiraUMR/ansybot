#!/bin/sh
python3 - <<'PY'
import pkgutil, sys
print('py', sys.version)
# find alibaba adapter
import os
roots = []
for p in sys.path:
    if p:
        roots.append(p)
print('path0', sys.path[:5])
for root, dirs, files in os.walk('/usr/local/lib'):
    for f in files:
        if 'alibaba' in f.lower() or 'dashscope' in f.lower():
            print(os.path.join(root, f))
PY
