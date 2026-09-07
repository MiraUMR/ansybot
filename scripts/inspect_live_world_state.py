import yaml
from pathlib import Path

p = Path("/opt/kirara-ai/data/workflows/chat/normal.yaml")
d = yaml.safe_load(p.read_text(encoding="utf-8"))
print("blocks:", [b["name"] for b in d["blocks"]])
sp = next(b for b in d["blocks"] if b["name"] == "system_prompt")
text = sp["params"]["text"]
print("has {world_state}:", "{world_state}" in text)
print("system_prompt wires:", sp.get("connected_to"))
idx = text.find("{world_state}")
print("placeholder index:", idx)
if idx >= 0:
    print("around placeholder:")
    print(text[max(0, idx - 250) : idx + 80])
else:
    print("TAIL:")
    print(text[-500:])
print("--- inject ---")
print(next((b for b in d["blocks"] if b["name"] == "inject_world_state"), None))
print("--- query ---")
print(next((b for b in d["blocks"] if b["name"] == "query_world_state"), None))
print("--- apply ---")
print(next((b for b in d["blocks"] if b["name"] == "apply_world_state"), None))
gm = next(b for b in d["blocks"] if b["name"] == "get_message")
print("get_message targets:", [w["target"] for w in gm.get("connected_to") or []])
llm = next(b for b in d["blocks"] if b["name"] == "llm_chat")
print("llm wires:", llm.get("connected_to"))
ctor = next(b for b in d["blocks"] if "Constructor" in b["name"] or b["type"] == "internal:chat_message_constructor")
print("constructor:", ctor["name"], ctor.get("connected_to"))
print("constructor incoming from:")
for b in d["blocks"]:
    for w in b.get("connected_to") or []:
        if w.get("target") == ctor["name"]:
            print(" ", b["name"], w)
