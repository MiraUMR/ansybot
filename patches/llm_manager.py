import random
from typing import Dict, List, Optional

from kirara_ai.config.global_config import GlobalConfig
from kirara_ai.events.event_bus import EventBus
from kirara_ai.events.llm import LLMAdapterLoaded, LLMAdapterUnloaded
from kirara_ai.ioc.container import DependencyContainer
from kirara_ai.ioc.inject import Inject
from kirara_ai.llm.adapter import LLMBackendAdapter
from kirara_ai.llm.llm_registry import LLMAbility, LLMBackendRegistry
from kirara_ai.llm.model_ref import (
    api_model_name,
    qualify_model,
    set_backend_names,
    split_model_ref,
)
from kirara_ai.logger import get_logger


class LLMManager:
    """
    跟踪、管理和调度模型后端。
    模型在 active_backends 中以「后端名/裸模型名」注册，避免跨平台同名冲突。
    """

    container: DependencyContainer
    config: GlobalConfig
    backend_registry: LLMBackendRegistry
    active_backends: Dict[str, List[LLMBackendAdapter]]
    event_bus: EventBus

    @Inject()
    def __init__(
        self,
        container: DependencyContainer,
        config: GlobalConfig,
        backend_registry: LLMBackendRegistry,
        event_bus: EventBus,
    ):
        self.container = container
        self.config = config
        self.backend_registry = backend_registry
        self.event_bus = event_bus
        self.logger = get_logger("LLMAdapter")
        self.active_backends = {}
        self.backends: Dict[str, LLMBackendAdapter] = {}

    def load_config(self):
        """加载配置文件中的所有启用的后端"""
        set_backend_names(b.name for b in (self.config.llms.api_backends or []))
        for backend in self.config.llms.api_backends:
            if backend.enable:
                self.logger.info(f"Loading backend: {backend.name}")
                try:
                    self.load_backend(backend.name)
                except Exception as e:
                    self.logger.error(f"Failed to load backend {backend.name}: {e}")

    def _model_key(self, backend_name: str, model: str) -> str:
        # model 可为上游完整 id（含厂商/），勿先 api_model_name 剥段
        return qualify_model(backend_name, model)

    def load_backend(self, backend_name: str):
        """
        加载指定的后端
        :param backend_name: 后端名称
        """
        backend = next(
            (b for b in self.config.llms.api_backends if b.name == backend_name), None
        )
        if not backend:
            raise ValueError(f"Backend {backend_name} not found in config")

        if not backend.enable:
            raise ValueError(f"Backend {backend_name} is not enabled")

        if backend_name in self.backends:
            raise ValueError(f"Backend {backend_name} is already loaded")

        adapter_class = self.backend_registry.get(backend.adapter)
        config_class = self.backend_registry.get_config_class(backend.adapter)

        if not adapter_class or not config_class:
            raise ValueError(f"Invalid adapter type: {backend.adapter}")

        # 创建适配器实例
        with self.container.scoped() as scoped_container:
            scoped_container.register(config_class, config_class(**backend.config))
            adapter = Inject(scoped_container).create(adapter_class)()
            adapter.backend_name = backend_name
            self.backends[backend_name] = adapter

            # 注册到每个支持的模型（带平台前缀）
            for model in backend.models:
                key = self._model_key(backend_name, model)
                if key not in self.active_backends:
                    self.active_backends[key] = []
                if adapter not in self.active_backends[key]:
                    self.active_backends[key].append(adapter)
                self.logger.debug(f"Registered model key={key} backend={backend_name}")
        self.event_bus.post(LLMAdapterLoaded(adapter=adapter, backend_name=backend_name))
        self.logger.info(f"Backend {backend_name} loaded successfully")

    async def unload_backend(self, backend_name: str):
        """
        卸载指定的后端
        :param backend_name: 后端名称
        """
        backend = next(
            (b for b in self.config.llms.api_backends if b.name == backend_name), None
        )
        if not backend:
            raise ValueError(f"Backend {backend_name} not found in config")

        backend_adapter = self.backends.get(backend_name)

        if not backend_adapter:
            raise ValueError(f"Backend {backend_name} not found")

        # 从所有模型中移除这个后端的适配器
        all_models = list(self.active_backends.keys())
        for model in all_models:
            if backend_adapter in self.active_backends[model]:
                self.active_backends[model].remove(backend_adapter)
            if len(self.active_backends[model]) == 0:
                self.active_backends.pop(model)
        backend_adapter = self.backends.pop(backend_name)
        self.event_bus.post(LLMAdapterUnloaded(backend_name=backend_name, adapter=backend_adapter))

    async def reload_backend(self, backend_name: str):
        """
        重新加载指定的后端
        :param backend_name: 后端名称
        """
        await self.unload_backend(backend_name)
        self.load_backend(backend_name)

    def is_backend_available(self, backend_name: str) -> bool:
        """
        检查后端是否可用
        :param backend_name: 后端名称
        :return: 后端是否可用
        """
        backend = next(
            (b for b in self.config.llms.api_backends if b.name == backend_name), None
        )
        if not backend:
            return False

        if not backend.enable:
            return False

        # 检查后端的所有模型是否都有可用的适配器
        return all(
            self._model_key(backend_name, model) in self.active_backends
            and len(self.active_backends[self._model_key(backend_name, model)]) > 0
            for model in backend.models
        )

    def get(self, backend_name: str) -> Optional[LLMBackendAdapter]:
        """
        获取指定后端的适配器实例
        :param backend_name: 后端名称
        :return: LLM适配器实例,如果没有找到则返回None
        """
        return self.backends.get(backend_name)

    def get_llm(self, model_id: str) -> Optional[LLMBackendAdapter]:
        """
        按模型引用取适配器。
        优先「后端/模型」；若只给裸名且仅有一个后端提供，则用之；多个则取配置顺序第一个并告警。
        """
        if not model_id:
            return None

        backend, bare = split_model_ref(model_id)
        if backend:
            key = qualify_model(backend, bare)
            adapters = self.active_backends.get(key) or []
            if adapters:
                return adapters[0]
            # 后端已加载但 key 未注册时，仍可直连该后端（模型名由上游校验）
            return self.backends.get(backend)

        # 裸名：精确旧键（兼容）或后缀匹配
        if model_id in self.active_backends and self.active_backends[model_id]:
            adapters = self.active_backends[model_id]
            if len(adapters) > 1:
                self.logger.warning(
                    f"ambiguous bare model={model_id} backends="
                    f"{[getattr(a, 'backend_name', '?') for a in adapters]}, using first"
                )
            return adapters[0]

        matches: List[LLMBackendAdapter] = []
        seen = set()
        for key, adapters in self.active_backends.items():
            if api_model_name(key) != bare:
                continue
            for adapter in adapters:
                aid = id(adapter)
                if aid in seen:
                    continue
                seen.add(aid)
                matches.append(adapter)
        if not matches:
            return None
        if len(matches) > 1:
            # 按 config 中后端顺序挑第一个
            order = {
                b.name: i for i, b in enumerate(self.config.llms.api_backends or [])
            }
            matches.sort(key=lambda a: order.get(getattr(a, "backend_name", ""), 999))
            self.logger.warning(
                f"ambiguous bare model={model_id} backends="
                f"{[getattr(a, 'backend_name', '?') for a in matches]}, "
                f"using {getattr(matches[0], 'backend_name', '?')}; "
                f"prefer '{qualify_model(getattr(matches[0], 'backend_name', ''), bare)}'"
            )
        return matches[0]

    def get_supported_models(self, ability: LLMAbility) -> List[str]:
        """
        获取所有支持的模型（带平台前缀）
        :return: 支持的模型列表
        """
        adapter_types = self.backend_registry.search_adapter_by_ability(ability)
        matched_backends = set()
        for backend_id, backends in self.active_backends.items():
            for backend in backends:
                for adapter_type in adapter_types:
                    if isinstance(backend, adapter_type):
                        matched_backends.add(backend_id)
                        break

        if not matched_backends:
            return []
        return list(matched_backends)

    def get_llm_id_by_ability(self, ability: LLMAbility) -> Optional[str]:
        """
        根据指定的能力获取严格符合要求的 LLM 适配器列表。
        :param ability: 指定的能力。
        :return: 符合要求的 LLM 适配器列表。
        """
        supported_models = self.get_supported_models(ability)
        if not supported_models:
            return None
        return random.choice(supported_models)
