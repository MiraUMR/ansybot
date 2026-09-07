import re

path = "/tmp/kirara_index.js"
with open(path, encoding="utf-8", errors="replace") as f:
    d = f.read()
print("len", len(d))
print("createWebHistory", d.count("createWebHistory"))
print("createWebHashHistory", d.count("createWebHashHistory"))
print("backend-api", d.count("/backend-api"))
print("/assets/", d.count("/assets/"))
print("history matches", re.findall(r"createWebHistory\([^)]*\)", d)[:8])
print("hash matches", re.findall(r"createWebHashHistory\([^)]*\)", d)[:8])
print("base matches", re.findall(r'base:"[^"]*"', d)[:10])
print("path samples", re.findall(r'path:"[^"]+"', d)[:30])
