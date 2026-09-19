"""角色所在地的此刻体感：东京分区实时天气 + 当地时钟。

人设只提供地区，不写死「闷 / 头发炸了 / 翻手机」这类反应句。
模型拿到数字和体感标签后自己组织，前后必须同一条因果。
数据源：Open-Meteo（JMA 网格，无需 key）。缓存 20 分钟。
"""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

try:
    from kirara_ai.logger import get_logger

    logger = get_logger("WorldState.Weather")
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("WorldState.Weather")

ROOT = Path("data/world_state/_weather")
_lock = threading.RLock()
_CACHE_MINUTES = 20
_TOKYO = ZoneInfo("Asia/Tokyo")

# 人设地区 → Open-Meteo 坐标。默认都在东京都，细分到角色常活动的区。
_REGIONS: Dict[str, Dict[str, Any]] = {
    "tokyo_toshima": {
        "label": "东京·丰岛（池袋一带）",
        "lat": 35.7295,
        "lon": 139.7109,
    },
    "tokyo_minato": {
        "label": "东京·港区一带",
        "lat": 35.6581,
        "lon": 139.7514,
    },
    "tokyo": {
        "label": "东京·都心",
        "lat": 35.6812,
        "lon": 139.7671,
    },
}

_CHARACTER_REGION: Dict[str, str] = {
    "anon": "tokyo_toshima",
    "soyo": "tokyo_minato",
}

# WMO weather_code → 短体感（给模型当标签，禁止当台词照抄）
_WMO: Dict[int, str] = {
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
    80: "阵雨",
    81: "阵雨",
    82: "强阵雨",
    95: "雷阵雨",
    96: "雷阵雨",
    99: "雷暴",
}


def _cid(character: str) -> str:
    cid = (character or "").strip().lower()
    return cid if cid in _CHARACTER_REGION else "soyo"


def _region_from_persona(character: str) -> str:
    try:
        from .persona_config import load_config

        ident = load_config(_cid(character)).get("identity") or {}
    except Exception:
        return ""
    for key in ("weather_region", "residence"):
        val = str(ident.get(key) or "").strip()
        if val:
            return val
    return ""


def region_id_for(character: str, override: str = "") -> str:
    raw = (override or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in _REGIONS:
        return raw
    aliases = (
        ("tokyo_toshima", ("toshima", "ikebukuro", "池袋", "丰岛", "豊島")),
        ("tokyo_minato", ("minato", "港区", "月之森")),
        ("tokyo", ("tokyo", "东京", "東京", "东京都", "東京都")),
    )
    for rid, keys in aliases:
        if any(k.lower() in raw for k in keys):
            return rid
    return _CHARACTER_REGION[_cid(character)]


def _path(rid: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in rid)[:40]
    return ROOT / f"{safe or 'tokyo'}.json"


def _load_cache(rid: str) -> Optional[dict]:
    path = _path(rid)
    with _lock:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    ts = str(data.get("fetched_at") or "")
    try:
        fetched = datetime.fromisoformat(ts)
    except Exception:
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=_TOKYO)
    if datetime.now(_TOKYO) - fetched > timedelta(minutes=_CACHE_MINUTES):
        return None
    return data


def _save_cache(rid: str, payload: dict) -> None:
    path = _path(rid)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_open_meteo(lat: float, lon: float) -> Optional[dict]:
    q = urllib.parse.urlencode(
        {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,cloud_cover,wind_speed_10m",
            "hourly": "temperature_2m,precipitation_probability,weather_code",
            "forecast_hours": "6",
            "timezone": "Asia/Tokyo",
        }
    )
    url = f"https://api.open-meteo.com/v1/forecast?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "kirara-qq-bot/weather"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning(f"open-meteo fetch failed: {exc}")
        return None


def _wmo_label(code: Any) -> str:
    try:
        return _WMO.get(int(code), "多云")
    except (TypeError, ValueError):
        return "多云"


def _feel(temp: float, apparent: float, humidity: float, precip: float, code: int) -> str:
    """从数字压成一个体感词，供口气用，不是播报词库。"""
    ref = apparent if apparent is not None else temp
    # 51/53/55=细雨/小雨/雨(毛毛雨到中雨)；56/57=冻雨；61/63/65=雨(强度递增)；
    # 66/67=冻雨；80-82=阵雨；95-99=雷雨。之前只挑了 61/63/65，漏掉 51/53/55，
    # 导致 sky 显示「小雨」时 feel 掉进下面的温度判断，判成「闷」。
    rain_codes = (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99)
    if precip >= 0.1 or code in rain_codes:
        # 有雨也按体感温度分层：夏秋换季常见的 18-24° 小雨不该跟盛夏闷雨、
        # 深秋冷雨用同一个「潮」字，那三种湿感完全不一样。
        if ref <= 12:
            return "湿冷"
        if ref < 18:
            return "凉潮"
        if ref < 24:
            return "潮爽"
        return "闷湿" if humidity >= 75 else "潮热"
    # 无雨：体感温度细分成更多档，别只有「热/冷/普通」三挡
    if ref >= 33:
        return "酷热"
    if ref >= 29:
        return "闷热" if humidity >= 65 else "燥热"
    if ref >= 24:
        return "温热" if humidity >= 65 else "暖"
    if ref >= 18:
        return "干爽" if humidity <= 45 else "舒适"
    if ref >= 12:
        return "凉"
    if ref >= 5:
        return "冷"
    return "寒冷"


def _slot(now: datetime) -> str:
    h = now.hour
    if 5 <= h < 8:
        return "清晨"
    if 8 <= h < 11:
        return "上午"
    if 11 <= h < 14:
        return "中午"
    if 14 <= h < 17:
        return "下午"
    if 17 <= h < 19:
        return "傍晚"
    if 19 <= h < 23:
        return "晚上"
    return "深夜"


_WEEKDAY = "一二三四五六日"


def clock_now() -> datetime:
    return datetime.now(_TOKYO)


def snapshot(character: str, region_override: str = "") -> Dict[str, Any]:
    """返回可注入的结构化此刻状态。天气拉取失败时仍给时钟。"""
    now = clock_now()
    rid = region_id_for(character, region_override or _region_from_persona(character))
    meta = _REGIONS[rid]
    out: Dict[str, Any] = {
        "region_id": rid,
        "region": meta["label"],
        "weekday": _WEEKDAY[now.weekday()],
        "clock": now.strftime("%H:%M"),
        "slot": _slot(now),
        "ok": False,
    }
    cached = _load_cache(rid)
    data = cached.get("data") if cached else None
    if data is None:
        fetched = _fetch_open_meteo(meta["lat"], meta["lon"])
        if fetched:
            payload = {
                "fetched_at": now.isoformat(timespec="seconds"),
                "region_id": rid,
                "data": fetched,
            }
            _save_cache(rid, payload)
            data = fetched
    if not data:
        return out
    cur = data.get("current") or {}
    try:
        temp = float(cur.get("temperature_2m"))
        apparent = float(cur.get("apparent_temperature", temp))
        humidity = float(cur.get("relative_humidity_2m", 60))
        precip = float(cur.get("precipitation") or 0)
        code = int(cur.get("weather_code") or 2)
    except (TypeError, ValueError):
        return out
    hourly = data.get("hourly") or {}
    pops = hourly.get("precipitation_probability") or []
    codes = hourly.get("weather_code") or []
    near_pop = None
    near_code = None
    try:
        if pops:
            near_pop = int(pops[1] if len(pops) > 1 else pops[0])
        if codes:
            near_code = int(codes[1] if len(codes) > 1 else codes[0])
    except (TypeError, ValueError):
        pass
    out.update(
        {
            "ok": True,
            "temp_c": round(temp),
            "apparent_c": round(apparent),
            "humidity": round(humidity),
            "sky": _wmo_label(code),
            "feel": _feel(temp, apparent, humidity, precip, code),
            "precip_mm": precip,
            "next_pop": near_pop,
            "next_sky": _wmo_label(near_code) if near_code is not None else "",
        }
    )
    return out


_WEATHER_TALK_RE = re.compile(
    r"("
    r"天气|气温|温度|几度|℃|度天|"
    r"下雨|下雨了|要下雨|在下雨|雨停|淋雨|好大的雨|细雨|小雨|阵雨|雷阵雨|打雷|"
    r"出太阳|太阳好大|好晒|阴天|多云|晴天|天晴|"
    r"好热(?!闹)|好冷(?!静|场)|好闷|好潮|潮爽|闷热|湿冷|凉潮|闷湿|燥热|酷热|"
    r"体感|湿度|"
    r"天色|窗外.{0,8}(雨|晴|阴|云|热|冷|潮)|"
    r"空气.{0,6}(潮|湿|闷热|好热|好冷)"
    r")"
)
_COOLDOWN_TURNS = 8
_COOLDOWN_MINUTES = 15


def user_mentioned_weather(text: str) -> bool:
    return bool(_WEATHER_TALK_RE.search(text or ""))


def reply_mentions_weather(text: str) -> bool:
    return user_mentioned_weather(text)


def _cd_path(character: str, group_id: str) -> Path:
    safe_c = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in (character or "anon")
    )[:40]
    safe_g = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in str(group_id or "dm")
    )[:80]
    return ROOT / f"cd_{safe_c}__{safe_g or 'dm'}.json"


def _cd_load(character: str, group_id: str) -> dict:
    path = _cd_path(character, group_id)
    with _lock:
        if not path.exists():
            return {"turn": 0, "last_weather_turn": -999, "last_weather_at": ""}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"turn": 0, "last_weather_turn": -999, "last_weather_at": ""}
    return {
        "turn": int(data.get("turn") or 0),
        "last_weather_turn": int(data.get("last_weather_turn") or -999),
        "last_weather_at": str(data.get("last_weather_at") or ""),
    }


def _cd_save(character: str, group_id: str, doc: dict) -> None:
    path = _cd_path(character, group_id)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "character": character,
                    "group_id": str(group_id),
                    "turn": int(doc.get("turn") or 0),
                    "last_weather_turn": int(doc.get("last_weather_turn") or -999),
                    "last_weather_at": str(doc.get("last_weather_at") or ""),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def _gap_cleared(character: str, group_id: str) -> bool:
    doc = _cd_load(character, group_id)
    turn = int(doc.get("turn") or 0)
    last_t = int(doc.get("last_weather_turn") or -999)
    if (turn - last_t) < _COOLDOWN_TURNS:
        return False
    raw = str(doc.get("last_weather_at") or "")
    if not raw:
        return True
    try:
        last_at = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=_TOKYO)
    return datetime.now(_TOKYO) - last_at >= timedelta(minutes=_COOLDOWN_MINUTES)


def weather_on_cooldown(
    character: str, group_id: str = "", user_text: str = ""
) -> bool:
    """群友没提天气，且本角色本群刚说过天气：应关掉闲聊天气。"""
    if user_mentioned_weather(user_text):
        return False
    if not group_id:
        return False
    return not _gap_cleared(character, group_id)


def note_weather_after_reply(
    character: str, group_id: str, reply: str, user_text: str = ""
) -> None:
    if not group_id:
        return
    doc = _cd_load(character, group_id)
    doc["turn"] = int(doc.get("turn") or 0) + 1
    if reply_mentions_weather(reply):
        doc["last_weather_turn"] = doc["turn"]
        doc["last_weather_at"] = datetime.now(_TOKYO).isoformat(timespec="seconds")
    _cd_save(character, group_id, doc)


def here_now_line(
    character: str, region_override: str = "", *, clock_only: bool = False
) -> str:
    """一行事实。给模型当体感底，不要当台词。"""
    snap = snapshot(character, region_override)
    bits = [
        snap["region"],
        f"周{snap['weekday']} {snap['clock']} {snap['slot']}",
    ]
    if clock_only:
        bits.append("天气冷却中，只给时钟，不要提冷热晴雨")
        return " ".join(bits)
    if snap.get("ok"):
        bits.append(
            f"{snap['feel']} {snap['temp_c']}°C/体感{snap['apparent_c']}° 湿度{snap['humidity']}% {snap['sky']}"
        )
        nxt = []
        if snap.get("next_sky") and snap["next_sky"] != snap["sky"]:
            nxt.append(f"随后转{snap['next_sky']}")
        pop = snap.get("next_pop")
        if isinstance(pop, int):
            if pop >= 50:
                nxt.append(f"几小时内可能下雨({pop}%)")
            elif pop <= 15:
                nxt.append("近几小时基本无雨")
        if nxt:
            bits.append("，".join(nxt))
    else:
        bits.append("天气暂不可用，只按当地时钟，不要编温度")
    return " ".join(bits)


def here_now_block(
    character: str,
    region_override: str = "",
    *,
    group_id: str = "",
    user_text: str = "",
) -> str:
    """注入块：事实 + 一条因果原则，不给例句。冷却中只留时钟。"""
    cool = weather_on_cooldown(character, group_id, user_text)
    line = here_now_line(character, region_override, clock_only=cool)
    if cool:
        return (
            "<here_now>\n"
            f"- {line}\n"
            "- WEATHER: OFF\n"
            "- 本轮禁止提天气、冷热、晴雨、潮闷、体感、天色。时钟只用来知道现在几点。\n"
            "- 闲聊用眼前别的事，不要用天气填空。\n"
            "</here_now>"
        )
    extra = "- 没必要提天气就别提。不要默认头发/红茶/吉他/同一件吃的来填空。\n"
    return (
        "<here_now>\n"
        f"- {line}\n"
        "- 这是此刻体感底，不是话题清单，不要播报数字、不要念地区名。\n"
        "- 写进口气时前后必须同一条因果：后半句解释前半句。"
        "动作和体感要互相说明，不要两截无关的事先拼在一起。\n"
        f"{extra}"
        "</here_now>"
    )
