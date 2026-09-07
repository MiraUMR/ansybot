from pathlib import Path
d = Path(r"E:\qq_bot\web\assets\index.js").read_text(encoding="utf-8", errors="replace")
i = d.find("function Ny(")
print(d[i:i+2500])
