import yaml
c = yaml.safe_load(open("/app/data/config.yaml"))
print("ims:")
for im in c.get("ims", []):
    print(im)
print("plugins", c.get("plugins"))
print("web", {k: v for k, v in (c.get("web") or {}).items() if k != "secret_key"})
