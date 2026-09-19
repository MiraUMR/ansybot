from plugins.momo_companion.momo_companion import (
    geocode,
    fetch_weather,
    clothing_and_travel,
    extract_city_from_weather,
    menu_text,
    _defaults,
)

print("city extract", extract_city_from_weather("北京明天天气怎么样"))
g = geocode("武汉")
print("geo", g)
wx = fetch_weather(g["lat"], g["lon"], False)
print("wx", wx)
print("advice", clothing_and_travel(wx))
print("menu ok", "称呼" in menu_text(_defaults()))
