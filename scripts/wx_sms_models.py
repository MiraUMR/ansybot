#!/usr/bin/env python3
import json
import urllib.request

raw = urllib.request.urlopen("http://127.0.0.1:8059/docs/swagger.json", timeout=15).read()
d = json.loads(raw.decode())
defs = d.get("definitions") or d.get("components", {}).get("schemas") or {}
for name in (
    "DeviceIdLoginModel",
    "PhoneLoginModel",
    "WxBindOpMobileForModel",
    "VerificationcodeSimpleParam",
):
    print("====", name)
    print(json.dumps(defs.get(name), ensure_ascii=False, indent=2)[:2000])
