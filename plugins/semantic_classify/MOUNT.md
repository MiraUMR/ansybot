"""
挂载说明（Kirara / Quart）

任务书中的 FastAPI 示例：
    from plugins.semantic_classify.routes import router as semantic_router
    app.include_router(semantic_router, prefix="/api/semantic-classify")

本仓库实际等价挂载（已在 GroupWorldStatePlugin.on_start 与
SemanticClassifyPlugin.on_start 中幂等调用）：

    from kirara_ai.plugins.semantic_classify.routes import mount_semantic_classify
    mount_semantic_classify(web_server.web_api_app)

鉴权使用 Kirara 的 require_auth（Session/Cookie），对应任务书 require_kirara_session()。

文档：
  OpenAPI JSON: /backend-api/api/semantic-classify/openapi.json
  Swagger UI:   /backend-api/api/semantic-classify/docs
"""
