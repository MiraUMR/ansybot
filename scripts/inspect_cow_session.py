#!/usr/bin/env python3
from pathlib import Path
for p in [
    "/app/models/session_manager.py",
    "/app/models/chatgpt/chat_gpt_session.py",
    "/app/channel/chat_message.py",
]:
    print("=" * 20, p)
    print(Path(p).read_text(encoding="utf-8")[:3500])
