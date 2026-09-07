"""Kirara Plugin 入口。"""
from __future__ import annotations

from kirara_ai.logger import get_logger
from kirara_ai.plugin_manager.plugin import Plugin
from kirara_ai.web.app import WebServer

from .routes import mount_semantic_classify

logger = get_logger("SemanticClassifyPlugin")


class SemanticClassifyPlugin(Plugin):
    """独立语义分类 API；数据读写 data/persona/{persona}/hobbies.yaml。"""

    web_server: WebServer

    def on_load(self):
        logger.info("SemanticClassifyPlugin loaded")

    def on_start(self):
        # 依赖注入可能尚未就绪；实际挂载由 GroupWorldStatePlugin 幂等完成
        ws = getattr(self, "web_server", None)
        if ws is None or getattr(ws, "web_api_app", None) is None:
            logger.info(
                "SemanticClassifyPlugin: web_server 未就绪，跳过自挂载"
                "（由 GroupWorldStatePlugin 挂载）"
            )
            return
        if mount_semantic_classify(ws.web_api_app):
            logger.info(
                "SemanticClassifyPlugin started: /api/semantic-classify "
                "(docs=/api/semantic-classify/docs)"
            )
        else:
            logger.info("SemanticClassifyPlugin: blueprint already mounted")

    def on_stop(self):
        logger.info("SemanticClassifyPlugin stopped")
