"""classify 接口 Prompt 模板渲染。"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence


def build_classify_prompt(
    *,
    category: Dict[str, Any],
    input_text: str,
) -> str:
    display_name = str(category.get("display_name") or category.get("id") or "")
    cid = str(category.get("id") or "")
    stance = str(category.get("reply_stance") or "soft")
    mode_hints: Sequence[str] = list(category.get("mode_hints") or [])
    sample_lines: Sequence[str] = list(category.get("sample_lines") or [])
    forbid_pivot = bool(category.get("forbid_pivot"))
    hints = ", ".join(str(x) for x in mode_hints if str(x).strip())
    samples = "\n".join(f'  - "{line}"' for line in sample_lines) or '  - ""'
    lock_line = "是 ⚠️" if forbid_pivot else "否"
    pivot_rule = (
        "→ ⚠️ 严禁将话题转向其他分类，必须在本分类语境完成回应"
        if forbid_pivot
        else "→ 允许自然过渡到其他相关话题"
    )
    return (
        f"## 当前语境分类: {display_name} ({cid})\n"
        f"回复姿态: {stance}\n"
        f"模式提示: {hints}\n"
        f"锁定话题: {lock_line}\n"
        f"\n"
        f"### 参考台词风格:\n"
        f"{samples}\n"
        f"\n"
        f"### 执行要求:\n"
        f'用户输入: "{input_text}"\n'
        f"→ 以「{stance}」姿态回应\n"
        f"→ 遵循模式提示: {hints}\n"
        f"{pivot_rule}\n"
        f"→ 以上仅为语境引导，不覆盖Base人格规则"
    )
