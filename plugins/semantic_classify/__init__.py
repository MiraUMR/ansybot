"""语义分类 API 包。

Kirara 插件入口见 `plugin.py`；路由见 `routes.py`。
"""
from __future__ import annotations

# 轻量导出，避免 import 本包时强依赖 kirara_ai（便于本地冒烟）
from .routes import mount_semantic_classify, router, semantic_bp  # noqa: F401

try:
    from .plugin import SemanticClassifyPlugin  # noqa: F401
except Exception:  # pragma: no cover
    SemanticClassifyPlugin = None  # type: ignore
