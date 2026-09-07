"""按群隔离的长期设定：关系阶段等会随剧情更新，并可在 QQ / 网页 / 文件里管理。"""

from pathlib import Path

from kirara_ai.logger import get_logger
from kirara_ai.memory.memory_manager import MemoryManager
from kirara_ai.plugin_manager.plugin import Plugin
from kirara_ai.web.app import WebServer
from kirara_ai.workflow.core.block.registry import BlockRegistry

from .blocks import (
    AppendSceneContext,
    ApplyWorldState,
    DialogueContext,
    ExtractUserWorldState,
    ExtractWorldState,
    FilterFallbackMemory,
    GateMemoryByMode,
    GatedChatMemoryStore,
    GuardCharacterReply,
    ManageWorldState,
    PersonaLayers,
    QuerySceneContext,
    QueryWorldState,
    load_persona_module,
    warm_persona_modules,
)
from .token_meter import format_static_modules
from .characters import immersion_config
from .memory_scopes import CharacterGroupScope
from .peer import PeerChainStore
from .routes import world_state_bp
from .scene_context import SceneContextStore
from .store import WorldStateStore
from .story import StorySessionStore

logger = get_logger("WorldStatePlugin")


class AnonGroupScope(CharacterGroupScope):
    def __init__(self):
        super().__init__("anon")


class SoyoGroupScope(CharacterGroupScope):
    def __init__(self):
        super().__init__("soyo")


class GroupWorldStatePlugin(Plugin):
    block_registry: BlockRegistry
    web_server: WebServer

    def on_load(self):
        store = WorldStateStore(Path("data/world_state"))
        peer = PeerChainStore(Path("data/world_state/_peer_chains"))
        imm = immersion_config()
        scene = SceneContextStore(
            Path("data/world_state/_scene"),
            maxlen=int(imm.get("scene_buffer_max") or 5),
        )
        story = StorySessionStore(Path("data/world_state/_story"))
        container = self.web_server.container
        container.register(WorldStateStore, store)
        container.register(PeerChainStore, peer)
        container.register(SceneContextStore, scene)
        container.register(StorySessionStore, story)
        try:
            memory_manager = container.resolve(MemoryManager)
            memory_manager.register_scope("anon_group", AnonGroupScope)
            memory_manager.register_scope("soyo_group", SoyoGroupScope)
        except Exception as exc:
            logger.warning(f"register character memory scopes failed: {exc}")

        for block_id, cls, label in (
            ("query", QueryWorldState, "长期记忆：读取本群设定"),
            ("apply", ApplyWorldState, "长期记忆：写入并剥离标记"),
            ("extract", ExtractWorldState, "长期记忆：根据回复抽取本群设定"),
            ("extract_user", ExtractUserWorldState, "长期记忆：无回复时按关键词抽取"),
            ("dialogue", DialogueContext, "语境：对话对象与环境旁白分流"),
            ("query_scene", QuerySceneContext, "场景：读取 current_scene"),
            ("persona_layers", PersonaLayers, "人设：分层按需注入"),
            ("append_scene", AppendSceneContext, "场景：写入环境旁白缓冲"),
            ("gated_memory", GatedChatMemoryStore, "记忆：可跳过环境旁白"),
            ("guard_reply", GuardCharacterReply, "人设：称呼与叙事内化校验"),
            ("filter_fallback_memory", FilterFallbackMemory, "记忆：fallback 过滤"),
            ("gate_memory", GateMemoryByMode, "记忆：按模式过滤查询结果"),
            ("manage", ManageWorldState, "长期记忆：管理命令"),
        ):
            full = f"world_state:{block_id}"
            if self.block_registry.get(full) is None:
                self.block_registry.register(block_id, "world_state", cls, label)
        sizes = warm_persona_modules(("anon", "soyo"))
        entries = []
        for key in sizes:
            cid, _, module = key.partition(":")
            entries.append((key, load_persona_module(cid, module)))
        try:
            logger.info(format_static_modules(entries))
        except Exception:
            logger.info(f"persona modules cached: {sizes}")
        logger.info("GroupWorldStatePlugin loaded")

    def on_start(self):
        self.web_server.web_api_app.register_blueprint(
            world_state_bp, url_prefix="/api/world-state"
        )
        from .children_routes import children_bp
        from .persona_routes import persona_bp
        self.web_server.web_api_app.register_blueprint(
            children_bp, url_prefix="/api/children-mode"
        )
        self.web_server.web_api_app.register_blueprint(
            persona_bp, url_prefix="/api/persona"
        )
        try:
            try:
                from kirara_ai.plugins.semantic_classify.routes import mount_semantic_classify
            except Exception:
                from semantic_classify.routes import mount_semantic_classify  # type: ignore

            if mount_semantic_classify(self.web_server.web_api_app):
                logger.info("semantic-classify API mounted at /api/semantic-classify")
        except Exception as exc:
            logger.warning(f"mount semantic-classify failed: {exc}")
        logger.info("GroupWorldStatePlugin started")

    def on_stop(self):
        logger.info("GroupWorldStatePlugin stopped")
