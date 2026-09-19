import json
import urllib.parse
import urllib.request

lat, lon = 30.29365, 120.16142
query = (
    "[out:json][timeout:20];"
    "("
    f'nwr["tourism"~"attraction|museum|gallery|viewpoint|zoo|theme_park"](around:8000,{lat:.4f},{lon:.4f});'
    f'nwr["historic"~"monument|castle|temple|memorial"](around:8000,{lat:.4f},{lon:.4f});'
    f'nwr["leisure"="park"](around:8000,{lat:.4f},{lon:.4f});'
    ");"
    "out center 25;"
)
body = urllib.parse.urlencode({"data": query}).encode()
req = urllib.request.Request(
    "https://overpass-api.de/api/interpreter",
    data=body,
    headers={"User-Agent": "momo-companion/1.0", "Content-Type": "application/x-www-form-urlencoded"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=25) as resp:
    data = json.loads(resp.read().decode("utf-8"))
names = []
for el in data.get("elements") or []:
    tags = el.get("tags") or {}
    name = tags.get("name:zh") or tags.get("name")
    if name:
        names.append(name)
print("count", len(data.get("elements") or []), "named", len(names))
print(names[:20])
