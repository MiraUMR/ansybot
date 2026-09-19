#!/usr/bin/env python3
"""Dump recent chase/peer-turn prompts from kirara logs."""
import subprocess
import re

out = subprocess.check_output(
    ["docker", "logs", "kirara-qq-bot", "--since", "25m"],
    stderr=subprocess.STDOUT,
    text=True,
    errors="replace",
)
keys = [
    "还不去追",
    "也好",
    "鞋带散着",
    "这算哪门子夸",
    "追到了就不算白跑",
    "一直在追",
]


def snippet(line: str) -> str:
    extra = []
    if "TOPIC_LOCK" in line:
        m = re.search(r"\[TOPIC_LOCK\](.*?)\[/TOPIC_LOCK\]", line)
        extra.append("TOPIC=" + (m.group(1) if m else "")[:240].replace("\\n", " | "))
    if "轻提开关" in line:
        m = re.search(r"轻提开关[=:]([A-Z0-9]+)", line)
        extra.append("SWITCH=" + (m.group(1) if m else "?"))
    if "本轮是 Bot 互聊" in line:
        extra.append("PEER_MODE")
    if "EXTERNAL_TRIGGER" in line:
        extra.append("TRIGGER")
    if "SCENE CONTINUE" in line or "scene_continue" in line:
        extra.append("SCENE")
    if "peer_distress" in line:
        extra.append("DISTRESS")
    if "ACTION: chase_now" in line:
        extra.append("CHASE_NOW")
    return " ".join(extra)


for line in out.splitlines():
    if not any(k in line for k in keys):
        continue
    kind = "REQ" if "Request:" in line else ("RESP" if "Response:" in line else "LOG")
    if kind == "LOG":
        if "style_guard" in line or "Matched rule" in line or "WorldState" in line:
            print("LOG", line[-320:])
            print("---")
        continue
    flags = snippet(line)
    if kind == "RESP":
        m = re.search(r"'content': '([^']*)'", line)
        body = (m.group(1) if m else line[-240:]).replace("\\n", " | ")[:300]
        print("RESP", flags)
        print(body)
        print("---")
        continue
    trig = ""
    m = re.search(r"触发内容：([^\n\\]+)", line)
    if m:
        trig = m.group(1)[:120]
    # character hint
    ch = ""
    if "千早爱音" in line[:800] or "soyorin" in line[:400]:
        ch = "maybe_anon"
    if "长崎素世" in line[:800] or "小爱音" in line[:400]:
        ch = (ch + "+soyo") if ch else "maybe_soyo"
    print("REQ", flags, ch, "trig=", trig)
    print("---")
