"""本地校验：Bestdori 说话模式 yaml 接到 voice_pack。"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "group_world_state"


def _load_plugin() -> tuple:
    pkg = types.ModuleType("group_world_state")
    pkg.__path__ = [str(PLUGIN)]
    sys.modules["group_world_state"] = pkg

    def load(name: str):
        spec = importlib.util.spec_from_file_location(
            f"group_world_state.{name}", PLUGIN / f"{name}.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"group_world_state.{name}"] = mod
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        return mod

    sm = load("speech_model")
    vp = load("voice_pack")
    return sm, vp


def check(label: str, cond: bool, extra: str = "") -> None:
    print(f"[{'OK ' if cond else 'FAIL'}] {label}{(' :: ' + extra) if extra else ''}")
    if not cond:
        sys.exit(1)


sm, vp = _load_plugin()
check("anon 称呼锁定", sm.lock_example("anon", "素世等等我") == "soyorin等等我")
check("soyo 称呼锁定", sm.lock_example("soyo", "爱音酱别闹") == "小爱音别闹")
check(
    "peer_safe 拦你",
    (not sm.peer_safe("你怎么了")) and sm.peer_safe("你们先走") and sm.peer_safe("soyorin走啊"),
)

anon_yaml = ROOT / "data/voice_patterns/anon.yaml"
soyo_yaml = ROOT / "data/voice_patterns/soyo.yaml"
check("anon.yaml 存在", anon_yaml.exists(), str(anon_yaml))
check("soyo.yaml 存在", soyo_yaml.exists(), str(soyo_yaml))

sm.reload_patterns()
ap = sm.load_pattern("anon")
sp = sm.load_pattern("soyo")
check("anon 有聊天语料", int(ap.get("n_chat") or 0) >= 40, str(ap.get("n_chat")))
check("soyo 有聊天语料", int(sp.get("n_chat") or 0) >= 40, str(sp.get("n_chat")))
check("anon 例句池", len(ap.get("plain") or []) >= 8 and len(ap.get("quirk") or []) >= 8)
check("soyo 例句池", len(sp.get("plain") or []) >= 8 and len(sp.get("quirk") or []) >= 8)

anon_line = vp.voice_line("anon")
soyo_line = vp.voice_line("soyo")
check("anon 声线含官方节奏", "官方台词节奏" in anon_line and "千早爱音" in anon_line, anon_line[:80])
check("soyo 声线含官方节奏", "官方台词节奏" in soyo_line and "长崎素世" in soyo_line, soyo_line[:80])

hit = sm.retrieve_examples("anon", "走啊现在去吃", daily=False, count=2)
check("按字面检索例句", len(hit) >= 1, " | ".join(hit))
tail = vp.style_tail("anon", "g", "走啊现在去吃")
check("style_tail 注入语感参考", "语感参考" in tail)
print("ok")
