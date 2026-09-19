import subprocess
import re

out = subprocess.check_output(
    ["docker", "logs", "kirara-qq-bot", "--since", "90m"],
    stderr=subprocess.STDOUT,
    text=True,
    errors="replace",
)
keys = [
    "谁说的",
    "鞋带",
    "追什么追",
    "反正明天",
    "麻烦死了",
    "她好像在哭",
    "快追上",
    "她要跑了",
    "不要你了",
    "纹额头",
]
for line in out.splitlines():
    hit = next((k for k in keys if k in line), None)
    if not hit:
        continue
    if "Response:" in line:
        m = re.search(r"'content': '([^']*)'", line)
        body = (m.group(1) if m else line[-400:]).replace("\\n", " | ")
        print("RESP", hit, ":", body[:500])
        print("---")
    elif "触发内容" in line:
        m = re.search(r"触发内容：([^\n\\]+)", line)
        print("TRIG", hit, ":", (m.group(1) if m else "")[:240])
    elif "'content':" in line and "Request:" in line:
        # skip huge request dumps except trigger snippet
        continue
    elif "Matched rule" in line:
        print("RULE", line[-200:])
