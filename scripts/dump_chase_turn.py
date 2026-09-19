import subprocess
import re

out = subprocess.check_output(
    ["docker", "logs", "kirara-qq-bot", "--since", "30m"],
    stderr=subprocess.STDOUT,
    text=True,
    errors="replace",
)
keys = ["快去追", "鞋带都还没系", "又不差这一会儿", "style_guard"]
for line in out.splitlines():
    if not any(k in line for k in keys):
        continue
    if "Request:" in line and "快去追" in line:
        m = re.search(r"触发内容：([^\n\\]+)", line)
        print("TRIG", (m.group(1) if m else "")[:200])
        if "peer_interaction" in line:
            print("  has peer_interaction")
        if "轻提开关" in line:
            sw = re.search(r"轻提开关[:=]([A-Z]+)", line)
            print("  switch", sw.group(1) if sw else "?")
        if "TOPIC_LOCK" in line:
            tm = re.search(r"\[TOPIC_LOCK\](.*?)\[/TOPIC_LOCK\]", line)
            print("  topic", (tm.group(1) if tm else "")[:180].replace("\\n", " | "))
        continue
    if "Response:" in line:
        m = re.search(r"'content': '([^']*)'", line)
        print("RESP", (m.group(1) if m else "")[:300].replace("\\n", " | "))
        print("---")
        continue
    if "style_guard" in line and "Request:" not in line and "messages" not in line[:60]:
        s = line
        if len(s) > 350:
            s = s[:120] + " ... " + s[-180:]
        print("GUARD", s[-320:])
