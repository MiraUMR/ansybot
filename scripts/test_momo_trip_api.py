import json
import urllib.parse
import urllib.request

UA = {"User-Agent": "momo-companion/1.0 (elderly travel helper)"}


def get(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


geo = get("https://geocoding-api.open-meteo.com/v1/search?name=%E6%9D%AD%E5%B7%9E&count=1&language=zh")
item = geo["results"][0]
lat, lon = item["latitude"], item["longitude"]
print("geo", item["name"], lat, lon)
wx = get(
    "https://api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&forecast_days=2&timezone=Asia/Shanghai"
    % (lat, lon)
)
print("wx", wx.get("daily", {}).get("weather_code"), wx.get("daily", {}).get("temperature_2m_max"))
q = urllib.parse.urlencode(
    {
        "action": "query",
        "list": "geosearch",
        "gscoord": "%s|%s" % (lat, lon),
        "gsradius": "7000",
        "gslimit": "8",
        "format": "json",
    }
)
wiki = get("https://zh.wikipedia.org/w/api.php?" + q)
titles = [x.get("title") for x in (wiki.get("query") or {}).get("geosearch") or []]
print("wiki", titles[:8])
