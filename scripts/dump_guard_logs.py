import subprocess

out = subprocess.check_output(
    ["docker", "logs", "kirara-qq-bot", "--since", "90m"],
    stderr=subprocess.STDOUT,
    text=True,
    errors="replace",
)
needles = (
    "style_guard",
    "violation",
    "retry_rewrite",
    "fallback",
    "third-person",
    "character_violations",
    "scrub",
)
for line in out.splitlines():
    if "Request:" in line or "messages" in line[:80]:
        continue
    if any(n in line for n in needles):
        # keep last 240 chars of log line without huge dumps
        s = line
        if len(s) > 400:
            s = s[:120] + " ... " + s[-200:]
        print(s)
