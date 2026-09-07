from pathlib import Path

for name in ("LLMView.js", "BasicSettings.js"):
    t = Path("/opt/kirara-ai/webui/assets", name).read_text(encoding="utf-8", errors="replace")
    print("====", name, "len", len(t))
    for needle in ("/assets/", "/backend-api"):
        start = 0
        while True:
            i = t.find(needle, start)
            if i < 0:
                break
            print(repr(t[max(0, i - 40) : i + 60]))
            start = i + 1
