from pathlib import Path
d = Path(r"E:\qq_bot\web\assets\index.js").read_text(encoding="utf-8", errors="replace")
# find a2= 
for needle in [",a2=", "a2=function", "function a2(", "a2=e=>", "a2=t=>", "const a2="]:
    i = d.find(needle)
    print(needle, i)
    if i >= 0:
        print(d[i:i+400])
        print("---")
