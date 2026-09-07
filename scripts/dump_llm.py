import yaml
c = yaml.safe_load(open("/app/data/config.yaml"))
print("defaults", c.get("defaults"))
for b in c.get("llms", {}).get("api_backends", []):
    print(b.get("name"), b.get("adapter"), "enable=", b.get("enable"), "models=", b.get("models"))
