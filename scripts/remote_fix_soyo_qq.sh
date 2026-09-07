#!/bin/bash
set -e
cd /opt/kirara-ai
python3 - <<'PY'
from pathlib import Path
import yaml
p = Path('data/characters.yaml')
data = yaml.safe_load(p.read_text(encoding='utf-8'))
data['characters']['soyo']['qq'] = '2838871582'
p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
print('soyo.qq=', data['characters']['soyo']['qq'])
PY
docker compose up -d --force-recreate --no-deps kirara-agent
sleep 8
docker logs --tail 25 kirara-qq-bot 2>&1 | grep -iE 'Bot .* Connected|not_only_at_peer|Started adapter|ERROR' | tail -20
