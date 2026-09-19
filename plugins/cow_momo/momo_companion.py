# encoding:utf-8
"""莫莫：天气、基础设定、按当地天气规划旅行线路。"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_message import ChatMessage
from common.log import logger
from plugins import *

_TZ = ZoneInfo("Asia/Shanghai")
_UA = "momo-companion/1.0"
_DATA_PATH = os.path.join(os.environ.get("COW_DATA_DIR", "/home/agent/.cow"), "momo_settings.json")
_LOCK = threading.RLock()

ADDRESS_PRESETS = [
    ("1", "姐"),
    ("2", "哥"),
    ("3", "叔叔"),
    ("4", "阿姨"),
    ("5", "老师"),
    ("6", "不称呼"),
]
_ADDRESS_BY_NUM = {n: name for n, name in ADDRESS_PRESETS}
_ADDRESS_NAMES = {name for _, name in ADDRESS_PRESETS}

_WMO = {
    0: "晴",
    1: "大部晴",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾",
    51: "细雨",
    53: "小雨",
    55: "雨",
    61: "小雨",
    63: "雨",
    65: "大雨",
    71: "小雪",
    73: "雪",
    75: "大雪",
    80: "阵雨",
    81: "阵雨",
    82: "强阵雨",
    95: "雷阵雨",
    96: "雷阵雨",
    99: "雷暴",
}

_WEATHER_RE = re.compile(
    r"(天气|气温|温度|几度|℃|下雨|带伞|穿什么|穿搭|出门|出行|冷不冷|热不热|加衣服|要穿|多少度)"
)
_TRIP_RE = re.compile(
    r"(规划.{0,8}(旅行|旅游|行程|路线|线路)|"
    r"(旅行|旅游).{0,6}(路线|线路|规划|行程)|"
    r"一日游|两日游|三日游|两天游|"
    r"去[\u4e00-\u9fff]{2,12}玩|"
    r"想去[\u4e00-\u9fff]{2,12}|"
    r"帮我安排.{0,8}(行程|路线|旅行))"
)
_TRIP_DEST_RES = [
    re.compile(r"(?:帮我)?规划(?:一下)?([\u4e00-\u9fff]{2,12}?)(?:的)?(?:旅行|旅游|行程|路线|线路)"),
    re.compile(r"([\u4e00-\u9fff]{2,12}?)(?:的)?(?:旅行|旅游)(?:路线|线路|规划|行程)"),
    re.compile(r"去([\u4e00-\u9fff]{2,12}?)(?:玩|转转|看看|旅游|旅行)"),
    re.compile(r"([\u4e00-\u9fff]{2,12}?)(?:一日游|两日游|三日游|两天游|两日|两天)"),
    re.compile(r"(?:想去|要去)([\u4e00-\u9fff]{2,12})"),
]
_MENU_RE = re.compile(
    r"^(设定|设置|我的设定|改设定|改称呼|基础设定|怎么改|修改设定)[？?。.!！]*$"
)
_ADDR_RE = re.compile(
    r"^(?:请)?(?:以后)?(?:就)?(?:称呼我|叫我|喊我)\s*[「『“\"]?(.+?)[」』”\"]?[吧啊呀呢了]*$"
)
_CITY_SET_RE = re.compile(
    r"^(?:我住|我家在|默认城市|把城市改成|城市改成)\s*(.+?)[吧啊呀呢了。.!！]*$"
)
_STYLE_SHORT_RE = re.compile(r"(说短一点|回复短一点|简洁一点|少说点)")
_STYLE_LONG_RE = re.compile(r"(说详细一点|多说一点|回复长一点)")
_TOMORROW_RE = re.compile(r"(明天|明日)")
_CITY_IN_WEATHER_RE = re.compile(
    r"(?:查(?:一下)?|看看)?\s*([\u4e00-\u9fff]{2,8}?)(?:市|县|区)?(?:的)?(?:明天|明日)?(?:的)?(?:天气|气温|温度|穿什么|出门)"
)


def _http_json(url: str, timeout: int = 8) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _wmo(code) -> str:
    try:
        return _WMO.get(int(code), "多云")
    except (TypeError, ValueError):
        return "多云"


def _load_all() -> dict:
    with _LOCK:
        try:
            with open(_DATA_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except FileNotFoundError:
            return {}
        except Exception as exc:
            logger.warning("[Momo] load settings failed: %s", exc)
            return {}
    return {}


def _save_all(data: dict) -> None:
    with _LOCK:
        os.makedirs(os.path.dirname(_DATA_PATH) or ".", exist_ok=True)
        tmp = _DATA_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _DATA_PATH)


def _uid(msg: ChatMessage) -> str:
    if getattr(msg, "is_group", False):
        return str(msg.actual_user_id or msg.from_user_id or "group")
    return str(msg.from_user_id or msg.other_user_id or "default")


def _defaults() -> dict:
    return {"address": "姐", "city": "", "city_label": "", "lat": None, "lon": None, "style": "short"}


def get_user(uid: str) -> dict:
    all_data = _load_all()
    row = dict(_defaults())
    row.update(all_data.get(uid) or {})
    return row


def save_user(uid: str, row: dict) -> None:
    all_data = _load_all()
    all_data[uid] = row
    _save_all(all_data)


def geocode(name: str) -> dict | None:
    q = urllib.parse.urlencode(
        {"name": name, "count": 5, "language": "zh", "format": "json"}
    )
    url = "https://geocoding-api.open-meteo.com/v1/search?" + q
    try:
        data = _http_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("[Momo] geocode failed: %s", exc)
        return None
    results = data.get("results") or []
    if not results:
        return None
    preferred = None
    for item in results:
        if str(item.get("country_code") or "") == "CN":
            preferred = item
            break
    item = preferred or results[0]
    parts = [item.get("name") or name]
    for key in ("admin1", "country"):
        val = item.get(key)
        if val and val not in parts:
            parts.append(val)
    return {
        "city": item.get("name") or name,
        "city_label": " ".join(parts),
        "lat": float(item["latitude"]),
        "lon": float(item["longitude"]),
    }


def fetch_weather(lat: float, lon: float, tomorrow: bool) -> dict | None:
    q = urllib.parse.urlencode(
        {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
            "hourly": "temperature_2m,precipitation_probability,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
            "forecast_days": "2",
            "timezone": "Asia/Shanghai",
        }
    )
    url = "https://api.open-meteo.com/v1/forecast?" + q
    try:
        data = _http_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("[Momo] weather failed: %s", exc)
        return None
    now = datetime.now(_TZ)
    if tomorrow:
        daily = data.get("daily") or {}
        try:
            code = int((daily.get("weather_code") or [None, None])[1])
            tmax = float((daily.get("temperature_2m_max") or [None, None])[1])
            tmin = float((daily.get("temperature_2m_min") or [None, None])[1])
            pop = int((daily.get("precipitation_probability_max") or [0, 0])[1] or 0)
            rain = float((daily.get("precipitation_sum") or [0, 0])[1] or 0)
        except (TypeError, ValueError, IndexError):
            return None
        mid = (tmax + tmin) / 2
        return {
            "when": "明天",
            "sky": _wmo(code),
            "temp_c": round(mid),
            "tmax": round(tmax),
            "tmin": round(tmin),
            "apparent_c": round(mid),
            "humidity": None,
            "precip_mm": rain,
            "pop": pop,
            "wind": None,
            "code": code,
        }
    cur = data.get("current") or {}
    try:
        temp = float(cur.get("temperature_2m"))
        apparent = float(cur.get("apparent_temperature", temp))
        humidity = float(cur.get("relative_humidity_2m", 60))
        precip = float(cur.get("precipitation") or 0)
        code = int(cur.get("weather_code") or 2)
        wind = float(cur.get("wind_speed_10m") or 0)
    except (TypeError, ValueError):
        return None
    pops = (data.get("hourly") or {}).get("precipitation_probability") or []
    pop = None
    try:
        if pops:
            idx = min(now.hour + 1, len(pops) - 1)
            pop = int(pops[idx])
    except (TypeError, ValueError):
        pass
    return {
        "when": "现在",
        "sky": _wmo(code),
        "temp_c": round(temp),
        "tmax": None,
        "tmin": None,
        "apparent_c": round(apparent),
        "humidity": round(humidity),
        "precip_mm": precip,
        "pop": pop,
        "wind": round(wind),
        "code": code,
    }


def clothing_and_travel(wx: dict) -> tuple[str, str]:
    temp = float(wx.get("apparent_c") if wx.get("apparent_c") is not None else wx["temp_c"])
    if wx.get("tmax") is not None and wx.get("tmin") is not None:
        temp = (float(wx["tmax"]) + float(wx["tmin"])) / 2
    code = int(wx.get("code") or 0)
    pop = int(wx.get("pop") or 0)
    rain = float(wx.get("precip_mm") or 0)
    wet = rain >= 0.2 or pop >= 50 or code in (51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99)
    snow = code in (71, 73, 75)
    if temp >= 32:
        clothes = "短袖薄衣，出门戴帽或打伞防晒"
    elif temp >= 28:
        clothes = "短袖就行，别穿太厚"
    elif temp >= 22:
        clothes = "长袖或薄外套，热了好脱"
    elif temp >= 16:
        clothes = "外套或薄毛衣"
    elif temp >= 10:
        clothes = "厚外套，怕冷再加围巾"
    elif temp >= 4:
        clothes = "棉衣或羽绒服，注意保暖"
    else:
        clothes = "厚羽绒服，帽子手套都带上"
    if snow:
        clothes += "，地面滑，鞋要防滑"
        travel = "少出门，出门走慢点，路面容易结冰"
    elif wet:
        clothes += "，别穿怕湿的鞋"
        travel = "记得带伞，路滑走稳，非必要少往远处跑"
    elif temp >= 33:
        travel = "中午别在外头晒着，多喝水，有头晕赶紧找阴凉"
    elif temp <= 4:
        travel = "能少出门就少出门，风大就别久站"
    else:
        travel = "出门没问题，看天色回来就行"
    return clothes, travel


def menu_text(row: dict) -> str:
    addr = row.get("address") or "姐"
    city = row.get("city_label") or row.get("city") or "还没设"
    style = "短" if row.get("style") == "short" else "普通"
    lines = [
        "可以改这些，回数字或按示例说就行：",
        "【称呼】1姐 2哥 3叔叔 4阿姨 5老师 6不称呼",
        "也可以直接说：称呼我老师",
        "【城市】说「我住北京」，以后查天气默认用它",
        "【回复】说「说短一点」或「说详细一点」",
        "【旅行】说「规划杭州旅行」或「明天苏州一日游」",
        f"现在：称呼「{addr}」，城市{city}，回复{style}。",
    ]
    return "\n".join(lines)


def _clean_addr(raw: str) -> str | None:
    name = (raw or "").strip(" 。.!！?？,，、")
    name = name.replace("吧", "").replace("啊", "").replace("呀", "")
    aliases = {
        "姐姐": "姐",
        "哥哥": "哥",
        "直呼其名": "不称呼",
        "不要称呼": "不称呼",
        "不用称呼": "不称呼",
        "名字": "不称呼",
    }
    name = aliases.get(name, name)
    if name in _ADDRESS_BY_NUM:
        return _ADDRESS_BY_NUM[name]
    if not name or len(name) > 8:
        return None
    if _WEATHER_RE.search(name):
        return None
    return name


def extract_city_from_weather(text: str) -> str:
    m = _CITY_IN_WEATHER_RE.search(text)
    if m:
        city = m.group(1)
        for junk in ("今天", "现在", "明天", "明日", "后天", "查一下", "看看"):
            city = city.replace(junk, "")
        city = city.strip("的了吧啊呀")
        if 2 <= len(city) <= 8:
            return city
    return ""


def extract_trip_dest(text: str) -> str:
    for pat in _TRIP_DEST_RES:
        m = pat.search(text)
        if not m:
            continue
        dest = m.group(1)
        for junk in ("今天", "明天", "明日", "后天", "帮我", "一下", "一个", "那里"):
            dest = dest.replace(junk, "")
        dest = dest.strip("的了吧啊呀去到在")
        if 2 <= len(dest) <= 12:
            return dest
    return ""


def trip_days(text: str) -> int:
    if re.search(r"(三日|三天|3天|三号)", text):
        return 2
    if re.search(r"(两日|两天|2天|二日)", text):
        return 2
    return 1


def _wet_code(code: int, pop: int, rain: float) -> bool:
    return rain >= 0.2 or pop >= 50 or code in (51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99)


def fetch_daily_weather(lat: float, lon: float, day_index: int) -> dict | None:
    """day_index 0=今天, 1=明天。"""
    q = urllib.parse.urlencode(
        {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max",
            "forecast_days": "3",
            "timezone": "Asia/Shanghai",
        }
    )
    url = "https://api.open-meteo.com/v1/forecast?" + q
    try:
        data = _http_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("[Momo] daily weather failed: %s", exc)
        return None
    daily = data.get("daily") or {}
    idx = 1 if day_index else 0
    try:
        code = int((daily.get("weather_code") or [])[idx])
        tmax = float((daily.get("temperature_2m_max") or [])[idx])
        tmin = float((daily.get("temperature_2m_min") or [])[idx])
        pop = int((daily.get("precipitation_probability_max") or [0, 0])[idx] or 0)
        rain = float((daily.get("precipitation_sum") or [0, 0])[idx] or 0)
        wind = float((daily.get("wind_speed_10m_max") or [0, 0])[idx] or 0)
    except (TypeError, ValueError, IndexError):
        return None
    when = "明天" if day_index else "今天"
    return {
        "when": when,
        "sky": _wmo(code),
        "temp_c": round((tmax + tmin) / 2),
        "tmax": round(tmax),
        "tmin": round(tmin),
        "apparent_c": round((tmax + tmin) / 2),
        "humidity": None,
        "precip_mm": rain,
        "pop": pop,
        "wind": round(wind),
        "code": code,
        "wet": _wet_code(code, pop, rain),
        "snow": code in (71, 73, 75),
    }


def _poi_kind(name: str, tags: dict | None = None) -> str:
    tags = tags or {}
    blob = (name or "") + " " + " ".join(str(v) for v in tags.values())
    indoor_keys = ("博物馆", "博物院", "美术馆", "纪念馆", "展览", "mall", "商场", "museum", "gallery", "theatre", "theater")
    if tags.get("tourism") in ("museum", "gallery", "hotel") or tags.get("amenity") in ("theatre", "library"):
        return "室内"
    if any(k in blob.lower() or k in blob for k in indoor_keys):
        return "室内"
    return "室外"


def _wiki_pois(lat: float, lon: float) -> list[dict]:
    q = urllib.parse.urlencode(
        {
            "action": "query",
            "list": "geosearch",
            "gscoord": f"{lat}|{lon}",
            "gsradius": "7000",
            "gslimit": "18",
            "format": "json",
        }
    )
    url = "https://zh.wikipedia.org/w/api.php?" + q
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "momo-companion/1.0 (elderly travel helper)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("[Momo] wiki pois failed: %s", exc)
        return []
    out = []
    skip = ("列表", "站", "线", "区", "县", "市", "省", "路", "街道", "大学", "学院", "中学", "小学", "医院", "村", "社区")
    for item in (data.get("query") or {}).get("geosearch") or []:
        title = str(item.get("title") or "").strip()
        if not title or any(title.endswith(s) for s in skip):
            continue
        try:
            out.append(
                {
                    "name": title,
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                    "kind": _poi_kind(title),
                    "src": "wiki",
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _overpass_pois(lat: float, lon: float) -> list[dict]:
    query = (
        "[out:json][timeout:18];"
        "("
        f'nwr["tourism"~"attraction|museum|gallery|viewpoint|zoo|theme_park"](around:8000,{lat:.4f},{lon:.4f});'
        f'nwr["historic"~"monument|castle|temple|memorial"](around:8000,{lat:.4f},{lon:.4f});'
        f'nwr["leisure"="park"](around:8000,{lat:.4f},{lon:.4f});'
        ");"
        "out center 20;"
    )
    url = "https://overpass-api.de/api/interpreter"
    body = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"User-Agent": _UA, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("[Momo] overpass pois failed: %s", exc)
        return []
    out = []
    for el in data.get("elements") or []:
        tags = el.get("tags") or {}
        name = str(tags.get("name:zh") or tags.get("name") or "").strip()
        if not name:
            continue
        lat2 = el.get("lat") or (el.get("center") or {}).get("lat")
        lon2 = el.get("lon") or (el.get("center") or {}).get("lon")
        try:
            out.append(
                {
                    "name": name,
                    "lat": float(lat2),
                    "lon": float(lon2),
                    "kind": _poi_kind(name, tags),
                    "src": "osm",
                }
            )
        except (TypeError, ValueError):
            continue
    return out


def fetch_pois(lat: float, lon: float) -> list[dict]:
    osm = _overpass_pois(lat, lon)
    wiki = _wiki_pois(lat, lon) if len(osm) < 6 else []
    merged = []
    seen = set()
    for item in osm + wiki:
        key = re.sub(r"\s+", "", item["name"])[:12]
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= 12:
            break
    return merged


def _dist2(a: dict, b: dict) -> float:
    return (a["lat"] - b["lat"]) ** 2 + (a["lon"] - b["lon"]) ** 2


def order_pois(pois: list[dict], start: dict) -> list[dict]:
    if len(pois) <= 1:
        return list(pois)
    coords = ";".join(f"{p['lon']:.5f},{p['lat']:.5f}" for p in [start, *pois])
    url = (
        "https://router.project-osrm.org/trip/v1/foot/"
        + coords
        + "?source=first&roundtrip=false&overview=false"
    )
    try:
        data = _http_json(url, timeout=8)
        wps = data.get("waypoints") or []
        if len(wps) == len(pois) + 1:
            ranked = []
            for poi, wp in zip(pois, wps[1:]):
                ranked.append((int(wp.get("waypoint_index") or 99), poi))
            ranked.sort(key=lambda x: x[0])
            return [p for _, p in ranked]
    except Exception as exc:
        logger.info("[Momo] osrm skip: %s", exc)
    remaining = list(pois)
    route = []
    cur = start
    while remaining:
        remaining.sort(key=lambda p: _dist2(cur, p))
        nxt = remaining.pop(0)
        route.append(nxt)
        cur = nxt
    return route


def pick_trip_stops(pois: list[dict], wx: dict, days: int) -> list[dict]:
    wet = bool(wx.get("wet") or wx.get("snow"))
    hot = float(wx.get("tmax") or wx.get("temp_c") or 20) >= 32
    cold = float(wx.get("tmin") or wx.get("temp_c") or 20) <= 6
    indoor = [p for p in pois if p.get("kind") == "室内"]
    outdoor = [p for p in pois if p.get("kind") != "室内"]
    need = 4 if days == 1 else 7
    if wet:
        seq = indoor + outdoor
    elif hot or cold:
        seq = []
        n = max(len(indoor), len(outdoor))
        for i in range(n):
            if i < len(outdoor):
                seq.append(outdoor[i])
            if i < len(indoor):
                seq.append(indoor[i])
    else:
        seq = outdoor + indoor
    picked = []
    seen = set()
    for p in seq:
        key = p["name"]
        if key in seen:
            continue
        seen.add(key)
        picked.append(p)
        if len(picked) >= need:
            break
    return picked


def trip_strategy(wx: dict) -> str:
    if wx.get("snow"):
        return "路滑，少走路，多排室内，行程宜短"
    if wx.get("wet"):
        return "有雨，上午室内、下午看雨势再出门，全程带伞，少走路"
    tmax = float(wx.get("tmax") or wx.get("temp_c") or 20)
    tmin = float(wx.get("tmin") or wx.get("temp_c") or 20)
    if tmax >= 32:
        return "天热，早上室外、中午进馆休息、傍晚再出门，多喝水"
    if tmin <= 6:
        return "天冷，户外别太久，中午进室内暖暖，穿厚点"
    return "天气尚可，上午室外走走，下午留一个歇脚的地方"


def _text_reply(content: str, e_context: EventContext) -> None:
    reply = Reply()
    reply.type = ReplyType.TEXT
    reply.content = content
    e_context["reply"] = reply
    e_context.action = EventAction.BREAK_PASS


def _to_llm(prompt: str, e_context: EventContext) -> None:
    e_context["context"].content = prompt
    e_context.action = EventAction.BREAK


@plugins.register(
    name="MomoCompanion",
    desire_priority=950,
    hidden=False,
    enabled=True,
    desc="莫莫天气、设定与旅行线路",
    version="0.2",
    author="momo",
)
class MomoCompanion(Plugin):
    def __init__(self):
        super().__init__()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        logger.info("[Momo] companion plugin inited path=%s", _DATA_PATH)

    def get_help_text(self, **kwargs):
        return (
            "天气：说「北京天气」或「明天出门穿什么」\n"
            "旅行：说「规划杭州旅行」或「明天苏州一日游」\n"
            "设定：发「设定」查看预设；「称呼我阿姨」「我住武汉」可直接改"
        )

    def on_handle_context(self, e_context: EventContext):
        if e_context["context"].type != ContextType.TEXT:
            return
        content = (e_context["context"].content or "").strip()
        if not content:
            return
        msg: ChatMessage = e_context["context"]["msg"]
        uid = _uid(msg)
        row = get_user(uid)

        if _MENU_RE.match(content):
            _text_reply(menu_text(row), e_context)
            return

        if content in _ADDRESS_BY_NUM:
            row["address"] = _ADDRESS_BY_NUM[content]
            save_user(uid, row)
            _text_reply(_confirm_addr(row), e_context)
            return

        m_addr = _ADDR_RE.match(content)
        if m_addr:
            name = _clean_addr(m_addr.group(1))
            if not name:
                _text_reply("这个称呼有点长，换个两三个字的试试？也可以回数字 1 到 6。", e_context)
                return
            row["address"] = name
            save_user(uid, row)
            _text_reply(_confirm_addr(row), e_context)
            return

        m_city = _CITY_SET_RE.match(content)
        if m_city:
            self._set_city(uid, row, m_city.group(1), e_context)
            return

        if _STYLE_SHORT_RE.search(content) and len(content) <= 16:
            row["style"] = "short"
            save_user(uid, row)
            _text_reply("好，我少说两句。", e_context)
            return
        if _STYLE_LONG_RE.search(content) and len(content) <= 16:
            row["style"] = "normal"
            save_user(uid, row)
            _text_reply("好，我稍微说细一点。", e_context)
            return

        if _TRIP_RE.search(content):
            self._handle_trip(uid, row, content, e_context)
            return

        if _WEATHER_RE.search(content):
            self._handle_weather(uid, row, content, e_context)
            return

        # 普通对话：把当前称呼/城市塞进提示，让模型按设定说
        addr = row.get("address") or "姐"
        style = row.get("style") or "short"
        length = "每次最多三句，总共不超过一百字" if style == "short" else "可以说细一点，但不要长篇"
        city = row.get("city_label") or row.get("city") or ""
        city_bit = f"对方常住{city}。" if city else ""
        if addr == "不称呼":
            call_bit = "不要用姐/哥/叔叔/阿姨等称呼，直接说话。"
        else:
            call_bit = f"用「{addr}」称呼对方。"
        e_context["context"].content = (
            f"（{call_bit}{city_bit}{length}不要提起这些括号里的设定。）\n{content}"
        )
        e_context.action = EventAction.CONTINUE

    def _set_city(self, uid: str, row: dict, raw: str, e_context: EventContext):
        name = (raw or "").strip(" 。.!！?？市")
        if len(name) < 2:
            _text_reply("城市名再清楚点，比如：我住北京。", e_context)
            return
        geo = geocode(name)
        if not geo:
            _text_reply(f"我没找着「{name}」这个地方，换个城市名再试试。", e_context)
            return
        row.update(geo)
        save_user(uid, row)
        _text_reply(f"记下了，以后查天气默认看{geo['city_label']}。想查的时候说「天气怎么样」就行。", e_context)

    def _handle_trip(self, uid: str, row: dict, content: str, e_context: EventContext):
        dest = extract_trip_dest(content)
        geo = None
        if dest:
            geo = geocode(dest)
        elif row.get("lat") and row.get("lon"):
            geo = {
                "city": row.get("city") or "",
                "city_label": row.get("city_label") or row.get("city") or "",
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
            }
        if not geo:
            _text_reply("想去哪儿玩？说「规划杭州旅行」或「明天苏州一日游」就行。", e_context)
            return
        days = trip_days(content)
        day0 = 1 if _TOMORROW_RE.search(content) else 0
        wx_list = []
        for i in range(days):
            wx = fetch_daily_weather(geo["lat"], geo["lon"], day0 + i)
            if wx:
                wx_list.append(wx)
        if not wx_list:
            _text_reply("这会儿天气查不上来，过几分钟再让我帮你排路线。", e_context)
            return
        pois = fetch_pois(geo["lat"], geo["lon"])
        start = {"lat": geo["lat"], "lon": geo["lon"]}
        picked = pick_trip_stops(pois, wx_list[0], days)
        ordered = order_pois(picked, start) if picked else []
        if days == 2 and len(ordered) >= 4:
            chunks = [ordered[: len(ordered) // 2], ordered[len(ordered) // 2 :]]
        else:
            chunks = [ordered]
        lines = []
        for i, wx in enumerate(wx_list):
            clothes, _travel = clothing_and_travel(wx)
            label = wx["when"]
            lines.append(
                f"{label}天气：{wx['sky']}，{wx['tmin']}～{wx['tmax']}℃，降雨概率{wx['pop']}%。{trip_strategy(wx)}"
            )
            lines.append(f"{label}穿衣：{clothes}")
            stops = chunks[i] if i < len(chunks) else []
            if stops:
                bits = [f"{j+1}.{s['name']}（{s['kind']}）" for j, s in enumerate(stops)]
                lines.append(f"{label}候选地点（已按路程排过）：" + "、".join(bits))
            else:
                lines.append(f"{label}没查到具体店名，按天气用公园/商场/博物馆大致安排，不要编造景区名字。")
        addr = row.get("address") or "姐"
        call_bit = "不要用称呼，直接说话。" if addr == "不称呼" else f"用「{addr}」称呼对方。"
        prompt = (
            f"请给中老年朋友做一份轻松的旅行线路，不要排太满，每段之间留歇脚。"
            f"{call_bit}按「上午/下午/晚上」写，每天最多三个点。"
            f"景点只能从下面候选名单里选，不要编新名字；没有名单就只给天气建议，不捏造景点。"
            f"结合当天天气决定室内还是室外。最后用一两句说穿衣和带不带伞。"
            f"口语、好懂，不要提API、数据来源或自己是AI。不要用英文缩写和网络词。\n"
            f"目的地：{geo['city_label']}，共{len(wx_list)}天。\n"
            + "\n".join(lines)
            + f"\n用户原话：{content}"
        )
        logger.info("[Momo] trip dest=%s days=%s stops=%s", geo.get("city_label"), days, len(ordered))
        _to_llm(prompt, e_context)

    def _handle_weather(self, uid: str, row: dict, content: str, e_context: EventContext):
        tomorrow = bool(_TOMORROW_RE.search(content))
        city_name = extract_city_from_weather(content)
        geo = None
        if city_name:
            geo = geocode(city_name)
            if geo:
                # 顺手记下，下次可少说地名
                if not row.get("city"):
                    row.update(geo)
                    save_user(uid, row)
        elif row.get("lat") and row.get("lon"):
            geo = {
                "city": row.get("city") or "",
                "city_label": row.get("city_label") or row.get("city") or "",
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
            }
        if not geo:
            _text_reply("想查哪儿的天气？说「北京天气」，或者说「我住上海」我帮你记住。", e_context)
            return
        wx = fetch_weather(geo["lat"], geo["lon"], tomorrow)
        if not wx:
            _text_reply("这会儿天气查不上来，过几分钟再问我一声。", e_context)
            return
        clothes, travel = clothing_and_travel(wx)
        addr = row.get("address") or "姐"
        call_bit = "不要用称呼，直接说话。" if addr == "不称呼" else f"用「{addr}」称呼对方。"
        style = row.get("style") or "short"
        length = "最多三句，总共不超过一百字" if style == "short" else "可以说细一点，仍要口语"
        if wx["when"] == "明天":
            fact = (
                f"地点：{geo['city_label']} 明天 {wx['sky']}，"
                f"{wx['tmin']}～{wx['tmax']}℃，降雨概率{wx['pop']}%"
            )
        else:
            hum = f"，湿度{wx['humidity']}%" if wx.get("humidity") is not None else ""
            wind = f"，风{wx['wind']}公里/时" if wx.get("wind") is not None else ""
            pop = f"，近几小时降雨概率{wx['pop']}%" if wx.get("pop") is not None else ""
            fact = (
                f"地点：{geo['city_label']} 现在 {wx['sky']}，"
                f"{wx['temp_c']}℃（体感{wx['apparent_c']}℃）{hum}{wind}{pop}"
            )
        prompt = (
            f"下面是刚查到的实况，请按人设回复。{call_bit}{length}。"
            f"先说天气，再给穿搭和出门建议。数字必须用下面这些，不要编造。"
            f"不要提API、数据来源或自己是AI。\n"
            f"{fact}\n"
            f"穿搭要点：{clothes}\n"
            f"出行要点：{travel}\n"
            f"用户原话：{content}"
        )
        logger.info("[Momo] weather %s %s", geo.get("city_label"), fact)
        _to_llm(prompt, e_context)


def _confirm_addr(row: dict) -> str:
    addr = row.get("address") or "姐"
    if addr == "不称呼":
        return "好，以后我不加称呼了。"
    return f"好，以后叫你{addr}。"
