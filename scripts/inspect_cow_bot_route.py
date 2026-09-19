#!/bin/sh
echo '=== web dirs ==='
ls /app/channel/web 2>/dev/null | head
find /app -maxdepth 3 -type d -name 'web*' 2>/dev/null | head
echo '=== py token logs ==='
grep -RIn --include='*.py' 'total_tokens' /app 2>/dev/null | grep -v __pycache__ | grep -v /tests/ | head -30
echo '=== html usage ==='
find /app -name '*.html' | head -40
