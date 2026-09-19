import inspect
from kirara_ai.web.app import WebServer
print("WebServer methods:", [m for m in dir(WebServer) if not m.startswith("_")])
print(inspect.getsource(WebServer.__init__)[:2500])
print("--- attrs ---")
src = inspect.getsource(WebServer)
print("has app:", "self.app" in src, "web_api_app" in src, "fastapi" in src.lower())
# print class annotations
print("annotations", getattr(WebServer, "__annotations__", {}))
