#!/usr/bin/env python3
import os, re, json

def mask(k):
    k = (k or "").strip().strip('"').strip("'")
    if not k:
        return "<empty>"
    return "len=%s prefix=%s suffix=%s" % (len(k), k[:8], k[-6:])

print("=== kirara yaml keys ===")
p = "/opt/kirara-ai/data/config.yaml"
text = open(p, encoding="utf-8").read()
for i, line in enumerate(text.splitlines(), 1):
    if "api_key" in line.lower() or "api_base" in line.lower() or "adapter:" in line or "name:" in line:
        if "api_key" in line.lower():
            k = line.split(":",1)[1].strip().strip('"').strip("'")
            print("%d api_key %s" % (i, mask(k)))
        else:
            print("%d %s" % (i, line.strip()[:120]))

print("=== adapter head ===")
ap = "/usr/local/lib/python3.11/site-packages/kirara_ai/plugins/llm_preset_adapters/alibabacloud_adapter.py"
print("exists_in_this_process", os.path.exists(ap))
