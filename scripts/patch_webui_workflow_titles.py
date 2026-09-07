"""Show Chinese block names as LiteGraph node titles in the workflow editor."""
from pathlib import Path
import sys

OLD = "I.id=G.name,I.pos=[G.position.x,G.position.y],a.add(I)"
NEW = (
    "I.id=G.name,"
    r"/[\u4e00-\u9fff]/.test(G.name)&&(I.title=G.name,I.size=I.computeSize()),"
    "I.pos=[G.position.x,G.position.y],a.add(I)"
)

roots = [Path(p) for p in sys.argv[1:]] or [
    Path("/opt/kirara-ai/webui"),
    Path(__file__).resolve().parents[1] / "web",
]


def patch_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    if "I.title=G.name" in text:
        return "already"
    if OLD not in text:
        return "missing"
    path.write_text(text.replace(OLD, NEW, 1), encoding="utf-8", errors="surrogateescape")
    return "patched"


changed = 0
for root in roots:
    if not root.exists():
        continue
    for path in root.rglob("WorkflowEditor.js"):
        status = patch_file(path)
        print(status, path)
        if status == "patched":
            changed += 1
print("files_changed", changed)
if changed == 0:
    sys.exit(1)
