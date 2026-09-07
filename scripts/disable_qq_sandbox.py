from pathlib import Path

p = Path("/opt/kirara-ai/data/config.yaml")
text = p.read_text(encoding="utf-8")
old = text
# Only flip the QQ adapter sandbox flag, not unrelated occurrences.
# The IM block has "sandbox: true" under qqbot config.
import re
new, n = re.subn(
    r"(adapter:\s*qqbot\s*\n(?:.*\n)*?\s*)sandbox:\s*true",
    r"\1sandbox: false",
    text,
    count=1,
)
if n != 1:
    raise SystemExit(f"sandbox replace count={n}")
p.write_text(new, encoding="utf-8")
print("sandbox set to false")
