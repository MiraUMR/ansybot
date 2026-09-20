#!/usr/bin/env python3
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = spec_from_file_location("voice_text", ROOT / "plugins/group_world_state/voice_text.py")
mod = module_from_spec(spec)
spec.loader.exec_module(mod)

failed = 0


class VoiceEl:
    description = "anon tts"

    def to_plain(self):
        return "[语音消息]"


class TextEl:
    text = "明天去吃"
    description = ""

    def to_plain(self):
        return "明天去吃"


class Msg:
    def __init__(self, elements, content=""):
        self.message_elements = elements
        self.content = content
        self.raw_message = None


def check(label, cond):
    global failed
    print(f"[{'OK ' if cond else 'FAIL'}] {label}")
    if not cond:
        failed += 1


only_voice = Msg([VoiceEl()], "[语音消息]")
mixed = Msg([TextEl(), VoiceEl()], "明天去吃")
plain = Msg([TextEl()], "明天去吃")

check("voice only", mod.is_voice_only(only_voice, "[语音消息]"))
check("mixed not only", not mod.is_voice_only(mixed, "明天去吃"))
check("plain text", not mod.is_voice_only(plain, "明天去吃"))
ja_voice = Msg([VoiceEl()], "えへっ、そよりん、呼んでるの、聞こえた？")
check("日文语音条当 voice only", mod.is_voice_only(ja_voice, "えへっ、そよりん、呼んでるの、聞こえた？"))
check("日文口播是 tts caption", mod.is_tts_caption("えへっ、あのんちゃん、聞こえた？"))
check("中文不是 tts caption", not mod.is_tts_caption("小爱音，今天没安排"))
check("语音条不算消息", mod.is_voice_bar_event(ja_voice, "えへっ、そよりん、呼んでるの、聞こえた？"))
check("中文加语音仍算那一句", not mod.is_voice_bar_event(mixed, "明天去吃"))
disp = (ROOT / "patches/dispatcher.py").read_text(encoding="utf-8")
check("调度层丢掉语音条", "is_voice_bar_event" in disp and "skip voice bar" in disp)
check("spoken strips voice", mod.spoken_text(mixed) == "明天去吃")
check("is voice element", mod.is_voice_element(VoiceEl()) and not mod.is_voice_element(TextEl()))

cv = (ROOT / "plugins/group_world_state/character_voice.py").read_text(encoding="utf-8")
skip_start = cv.find("_SKIP_VOICE_MODES")
skip_blob = cv[skip_start:skip_start + 220] if skip_start >= 0 else ""
check("peer/env_peer voice on", '"peer"' not in skip_blob and '"env_peer"' not in skip_blob)
check("env/story still skip", '"env"' in skip_blob and '"story"' in skip_blob)
check("voice scheduled async", "_schedule_voice" in cv and "run_coroutine_threadsafe" in cv)
anon = (ROOT / "data/workflows/chat/anon.yaml").read_text(encoding="utf-8")
soyo = (ROOT / "data/workflows/chat/soyo.yaml").read_text(encoding="utf-8")
check("anon mode→voice", "target: attach_character_voice" in anon)
check("soyo mode→voice", "target: attach_character_voice" in soyo)
check("anon text send first", "target: SendUserBot" in anon.split("name: ChatResponseConverter_23c2qz")[1].split("- type:")[0])
check("soyo text send first", "target: SendSoyoBot" in soyo.split("name: ChatResponseConverter_23c2qz")[1].split("- type:")[0])
attach_anon = anon.split("name: attach_character_voice")[1].split("- type:")[0] if "name: attach_character_voice" in anon else anon
attach_soyo = soyo.split("name: attach_character_voice")[-1]
check("anon voice not on send path", "target: SendUserBot" not in attach_anon)
check("soyo voice not on send path", "target: SendSoyoBot" not in attach_soyo)

jp_spec = spec_from_file_location("ja_phrases", ROOT / "plugins/group_world_state/ja_phrases.py")
jp = module_from_spec(jp_spec)
jp_spec.loader.exec_module(jp)
call_clip = jp.first_voice_clip("soyorin——！中午要不要一起出去逛逛嘛，我昨天看到一家新开的甜品店！")
check("keep vocative name", "逛逛" in call_clip and "soyorin" in call_clip.lower())
ask_clip = jp.first_voice_clip("诶？！要去喊soyorin出去玩吗——\n\n……也不是不行啦，反正她今天也没安排")
check("keep 语气词 and name", "诶" in ask_clip and "soyorin" in ask_clip.lower())
locked = jp.normalize_ja_for_tts("あのん、そよりん行こう", "soyo")
check("soyo 称同伴 あのんちゃん", "あのんちゃん" in locked and "anon" not in locked.lower())
check("soyo 不自称 そよりん", "そよりん" not in locked and "私" in locked)
anon_self = jp.normalize_ja_for_tts("あのんちゃん、行こうよ", "anon")
check("anon 不自称 あのんちゃん", "あのんちゃん" not in anon_self and "あたし" in anon_self)
anon_peer = jp.normalize_ja_for_tts("soyorin、聞こえた？", "anon")
check("anon 称同伴 そよりん", "そよりん" in anon_peer and "soyorin" not in anon_peer.lower())
space_keep = jp.normalize_ja_for_tts("anon chan、行こうよ", "soyo")
check("soyo 把 romaji 改假名", "あのんちゃん" in space_keep and "anon" not in space_keep.lower())
laugh = jp.normalize_ja_for_tts("えへへへ、soyorin～聞こえた？", "anon")
check("笑声收短", "えへっ" in laugh and "えへへ" not in laugh)
check("笑声后接假名称呼", "そよりん" in laugh and "soyorin" not in laugh.lower())
check("reject leftover 什么", jp.ja_has_zh_leftover("耳にいい什么の。", "顺耳什么啊"))
check("reject leftover 嘿嘿", jp.ja_has_zh_leftover("え、突然发语音过来嘿嘿ー。", "突然发语音过来嘿嘿"))
check(
    "accept complete ja",
    jp.is_spoken_japanese("えへっ、そよりん、呼んでるの、聞こえた？", "嘿嘿，soyorin听到我叫你了吗"),
)
check("reject mixed ja", not jp.is_spoken_japanese("あ、soyorin突然发语音过来、。", "突然发语音过来"))

check("siliconflow clip", "_sf_clip_and_translate" in cv and "siliconflow.cn" in cv)
check("name kana rule", "あのんちゃん" in cv and "そよりん" in cv)
check("anon 禁止自称 anonchan", "禁止自称「あのんちゃん」" in cv and "あたし" in cv)
check("laugh short in prompt", "えへっ" in cv and "あはっ" in cv)
check("complete sentence prompt", "完整、自然" in cv and "Qwen/Qwen2.5-72B-Instruct" in cv)

if failed:
    raise SystemExit(f"{failed} failed")
print("all passed")
