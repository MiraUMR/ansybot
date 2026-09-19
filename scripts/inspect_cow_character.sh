#!/bin/sh
grep -rn character_desc /app --include='*.py' | grep -v __pycache__ | grep -v /tests/ | head -50
echo '===session class==='
grep -rn 'class ChatGPTSession\|system_prompt\|character_desc' /app/bot /app/models --include='*.py' | grep -v __pycache__ | head -40
echo '===event==='
sed -n '1,80p' /app/plugins/event.py
