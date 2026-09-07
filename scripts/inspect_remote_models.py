from pathlib import Path
import yaml
d = yaml.safe_load(Path("/opt/kirara-ai/data/config.yaml").read_text(encoding="utf-8"))
print("defaults", d.get("defaults"))
for b in d.get("llms", {}).get("api_backends", []) or []:
    models = b.get("models") or []
    print("backend", b.get("name"), "enable", b.get("enable"), "count", len(models), "type0", type(models[0]).__name__ if models else None)
    print("sample", models[:15])
    vl = []
    for m in models:
        name = m if isinstance(m, str) else (m.get("id") or m.get("name") if isinstance(m, dict) else str(m))
        low = (name or "").lower()
        if any(x in low for x in ("-vl", "vl-", "vision", "qwen-vl")):
            vl.append(name)
    print("vl", vl[:20], "vl_count", len(vl))
