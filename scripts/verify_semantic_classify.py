"""语义分类 API 本地冒烟（不依赖 Kirara 进程）。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins"))

from semantic_classify.prompt_builder import build_classify_prompt  # noqa: E402
from semantic_classify.schemas import (  # noqa: E402
    CategoryCreate,
    CategoryUpdate,
    label_to_priority,
    priority_to_label,
)
from semantic_classify import yaml_store as store  # noqa: E402


def check(name: str, cond: bool, detail: str = ""):
    if cond:
        print(f"[OK ] {name}")
    else:
        print(f"[FAIL] {name} :: {detail}")
        raise SystemExit(1)


def main():
    check("priority map", priority_to_label(5) == "high" and label_to_priority("critical") == 6)
    prompt = build_classify_prompt(
        category={
            "id": "band_practice",
            "display_name": "乐队与练习",
            "reply_stance": "engage",
            "mode_hints": ["direct", "peer"],
            "sample_lines": ["今天练到九点。"],
            "forbid_pivot": True,
        },
        input_text="今天练团好累啊",
    )
    check("prompt template", "当前语境分类: 乐队与练习" in prompt and "严禁将话题转向" in prompt)

    with tempfile.TemporaryDirectory() as tmp:
        store.PERSONA_ROOT = Path(tmp)
        # seed soyo
        soyo = Path(tmp) / "soyo"
        soyo.mkdir()
        (soyo / "hobbies.yaml").write_text(
            "detector:\n  mode: hybrid\n  embed_model: text-embedding-v3\n"
            "  embed_threshold: 0.45\n  keyword_min_score: 8\n"
            "categories:\n"
            "- id: idle_ambient\n  display_name: 无爱好命中\n  priority: 1\n"
            "  keywords: []\n  aliases: []\n  reply_stance: deflect\n"
            "  mode_hints: [env]\n  sample_lines: ['冷。']\n  forbid_pivot: false\n"
            "- id: band_practice\n  display_name: 乐队\n  priority: 5\n"
            "  keywords: [排练]\n  aliases: [琴]\n  reply_stance: engage\n"
            "  mode_hints: [direct]\n  sample_lines: ['练。']\n  forbid_pivot: true\n",
            encoding="utf-8",
        )
        cats = store.list_categories("soyo")
        check("list categories", len(cats) == 2)
        band = next(c for c in cats if c.id == "band_practice")
        check("trigger merge", band.trigger_words == ["排练", "琴"])
        check("priority label", band.priority == "high")

        created = store.create_category(
            "soyo",
            CategoryCreate(
                display_name="测试场景",
                priority="medium",
                trigger_words=["关键词一", "ab", "Hello"],
                reply_stance="soft",
                mode_hints=["direct"],
                sample_lines=["示例"],
                forbid_pivot=False,
            ),
        )
        check("create id suffix", "_" in created.id and len(created.id.split("_")[-1]) == 4)
        # ab / Hello -> aliases; 关键词一 -> keywords
        raw = store.get_category("soyo", created.id)
        check("split keywords", "关键词一" in (raw.get("keywords") or []))
        check("split aliases", "ab" in (raw.get("aliases") or []) and "Hello" in (raw.get("aliases") or []))

        try:
            store.delete_category("soyo", "idle_ambient")
            check("idle delete blocked", False)
        except store.YamlStoreError as e:
            check("idle delete blocked", e.code == 409)

        try:
            store.update_category(
                "soyo", "idle_ambient", CategoryUpdate(reply_stance="engage")
            )
            check("idle stance blocked", False)
        except store.YamlStoreError as e:
            check("idle stance blocked", e.code == 409)

        cfg = store.get_detector_config("soyo")
        check("sensitivity", cfg["sensitivity"] == 45)
        cfg2 = store.update_detector_config("soyo", {"sensitivity": 60})
        check("sensitivity write", cfg2["sensitivity"] == 60)
        doc = store.load_doc("soyo", force=True)
        check("threshold write", abs(float(doc["detector"]["embed_threshold"]) - 0.6) < 1e-6)

        # anon isolation empty
        anon_list = store.list_categories("anon")
        check("anon empty", anon_list == [])

    print("ALL PASS")


if __name__ == "__main__":
    main()
