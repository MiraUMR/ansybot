"""Pydantic 请求/响应模型与 priority 映射。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

PriorityLabel = Literal["low", "medium", "high", "critical"]
# 内置四档 + 允许自定义 id（字母数字下划线短横线）
ReplyStance = str

BUILTIN_REPLY_STYLES: Dict[str, str] = {
    "engage": "积极回应",
    "soft": "温柔敷衍",
    "deflect": "转移话题",
    "ignore": "无视",
}

_STANCE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def normalize_reply_stance(raw: Any, *, default: str = "soft") -> str:
    s = str(raw or "").strip().lower().replace(" ", "_")
    if not s:
        return default
    if not _STANCE_ID_RE.match(s):
        raise ValueError(
            f"无效 reply_stance: {raw!r}（需小写字母开头，仅 a-z0-9_-，最长32）"
        )
    return s

PRIORITY_TO_LABEL: Dict[int, PriorityLabel] = {
    1: "low",
    3: "medium",
    5: "high",
    6: "critical",
}
LABEL_TO_PRIORITY: Dict[str, int] = {
    "low": 1,
    "medium": 3,
    "high": 5,
    "critical": 6,
}


def priority_to_label(raw: Any) -> PriorityLabel:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return "medium"
    return PRIORITY_TO_LABEL.get(n, "medium")


def label_to_priority(label: Any) -> int:
    key = str(label or "").strip().lower()
    if key not in LABEL_TO_PRIORITY:
        raise ValueError(f"无效 priority 值: {label!r}")
    return LABEL_TO_PRIORITY[key]


class CategoryOut(BaseModel):
    id: str
    display_name: str
    priority: PriorityLabel
    trigger_words: List[str] = Field(default_factory=list)
    reply_stance: str = "soft"
    mode_hints: List[str] = Field(default_factory=list)
    sample_lines: List[str] = Field(default_factory=list)
    forbid_pivot: bool = False


class CategoryCreate(BaseModel):
    display_name: str = Field(min_length=1)
    priority: PriorityLabel = "medium"
    trigger_words: List[str] = Field(default_factory=list)
    reply_stance: str = "soft"
    mode_hints: List[str] = Field(default_factory=list)
    sample_lines: List[str] = Field(default_factory=list)
    forbid_pivot: bool = False

    @field_validator("display_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("display_name 不能为空")
        return s

    @field_validator("reply_stance")
    @classmethod
    def _norm_stance(cls, v: str) -> str:
        return normalize_reply_stance(v)


class CategoryUpdate(BaseModel):
    display_name: Optional[str] = None
    priority: Optional[PriorityLabel] = None
    trigger_words: Optional[List[str]] = None
    reply_stance: Optional[str] = None
    mode_hints: Optional[List[str]] = None
    sample_lines: Optional[List[str]] = None
    forbid_pivot: Optional[bool] = None

    @field_validator("reply_stance")
    @classmethod
    def _norm_stance(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return normalize_reply_stance(v)


class ReplyStyleCreate(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=40)
    # 自定义风格落到哪条内置行为轨：engage|soft|deflect|ignore
    base: str = "soft"

    @field_validator("id")
    @classmethod
    def _norm_id(cls, v: str) -> str:
        return normalize_reply_stance(v)

    @field_validator("label")
    @classmethod
    def _strip_label(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("label 不能为空")
        return s

    @field_validator("base")
    @classmethod
    def _norm_base(cls, v: str) -> str:
        b = normalize_reply_stance(v, default="soft")
        if b not in BUILTIN_REPLY_STYLES:
            raise ValueError("base 仅允许 engage|soft|deflect|ignore")
        return b


class ReplyStyleOut(BaseModel):
    id: str
    label: str
    builtin: bool = False
    base: str = "soft"


class ClassifyIn(BaseModel):
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def _strip_text(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("text 不能为空")
        return s


class MatchedCategory(BaseModel):
    id: str
    display_name: str
    reply_stance: str


class ClassifyOut(BaseModel):
    matched_category: MatchedCategory
    confidence: float
    is_hit: bool
    generated_prompt: str


class DetectorConfigOut(BaseModel):
    sensitivity: int
    embed_model: str
    mode: str


class DetectorConfigUpdate(BaseModel):
    sensitivity: Optional[int] = Field(default=None, ge=0, le=100)
    embed_model: Optional[str] = None
    mode: Optional[str] = None


class ErrorOut(BaseModel):
    error: str
    code: int
