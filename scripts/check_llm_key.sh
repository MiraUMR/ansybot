#!/bin/sh
echo '=== adapters ==='
ls /usr/local/lib/python3.11/site-packages/kirara_ai/plugins/llm_preset_adapters/ | head
grep -l Alibaba /usr/local/lib/python3.11/site-packages/kirara_ai/plugins/llm_preset_adapters/*.py 2>/dev/null
echo '=== key len in qq config ==='
python3 - <<'PY'
from pathlib import Path
p=Path('/app/data/config.yaml')
text=p.read_text(encoding='utf-8')
for line in text.splitlines():
    if 'api_key:' in line and 'sk-' in line:
        k=line.split('api_key:',1)[1].strip().strip('"').strip("'")
        print('len', len(k), 'prefix', k[:8], 'suffix', k[-6:])
        break
PY
