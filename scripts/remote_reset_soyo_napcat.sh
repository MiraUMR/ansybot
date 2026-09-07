#!/bin/bash
set -e
cd /opt/kirara-ai

echo "Stopping napcat-soyo only (napcat-qq untouched)..."
docker compose stop napcat-soyo

echo "Backing up and clearing soyo QQ session..."
ts=$(date +%Y%m%d_%H%M%S)
mkdir -p /opt/kirara-ai/backups
tar -czf "/opt/kirara-ai/backups/napcat-soyo-qq-$ts.tgz" -C /opt/kirara-ai/napcat-soyo QQ config 2>/dev/null || true

# keep reverse WS + webui; drop account-bound files and session
rm -rf /opt/kirara-ai/napcat-soyo/QQ
mkdir -p /opt/kirara-ai/napcat-soyo/QQ
rm -f /opt/kirara-ai/napcat-soyo/config/napcat_*.json \
      /opt/kirara-ai/napcat-soyo/config/onebot11_*.json \
      /opt/kirara-ai/napcat-soyo/config/napcat.json 2>/dev/null || true

# ensure base onebot + webui remain
python3 - <<'PY'
import json
from pathlib import Path
cfg = Path('/opt/kirara-ai/napcat-soyo/config')
onebot = {
  "network": {
    "httpServers": [],
    "httpSseServers": [],
    "httpClients": [],
    "websocketServers": [],
    "websocketClients": [{
      "enable": True,
      "name": "kirara",
      "url": "ws://kirara-qq-bot:8080/im/websocket/onebot/qquser02/ws",
      "reportSelfMessage": False,
      "messagePostFormat": "array",
      "token": "bEA-8C8ho1j01r-qa9yT2g_rhH7exui3",
      "debug": False,
      "heartInterval": 30000,
      "reconnectInterval": 5000
    }],
    "plugins": []
  },
  "musicSignUrl": "",
  "enableLocalFile2Url": False,
  "parseMultMsg": False
}
(cfg / 'onebot11.json').write_text(json.dumps(onebot, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
webui = {
  "host": "0.0.0.0",
  "prefix": "/qqbot/napcat-soyo",
  "port": 6099,
  "token": "SoyoWebUI_7kQm2pLx9nR4vW8c",
  "loginRate": 3
}
(cfg / 'webui.json').write_text(json.dumps(webui, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('rewrote onebot11.json + webui.json')
PY

# clear soyo.qq until new account connects
python3 - <<'PY'
from pathlib import Path
import yaml
p = Path('/opt/kirara-ai/data/characters.yaml')
data = yaml.safe_load(p.read_text(encoding='utf-8'))
data['characters']['soyo']['qq'] = ''
p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
print('cleared soyo.qq')
PY

docker compose up -d --no-deps napcat-soyo
sleep 6
docker logs napcat-soyo 2>&1 | grep -iE 'WebUi Token|二维码|qrcode|login' | tail -8
echo "Ready for new QR login on :6100"
