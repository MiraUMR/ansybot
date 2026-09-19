#!/usr/bin/env python3
import json
import urllib.request
raw = urllib.request.urlopen("http://127.0.0.1:8059/docs/swagger.json", timeout=15).read()
d = json.loads(raw.decode())
print(json.dumps(d.get("definitions", {}).get("GetLoginQrCodeModel"), ensure_ascii=False, indent=2))
