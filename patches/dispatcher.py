from kirara_ai.im.adapter import IMAdapter
from kirara_ai.im.manager import IMManager
from kirara_ai.im.message import IMMessage
from kirara_ai.ioc.container import DependencyContainer
from kirara_ai.logger import get_logger
from kirara_ai.workflow.core.dispatch.models.dispatch_rules import CombinedDispatchRule
from kirara_ai.workflow.core.dispatch.registry import DispatchRuleRegistry
from kirara_ai.workflow.core.execution.executor import WorkflowExecutor
from kirara_ai.workflow.core.workflow.base import Workflow
from kirara_ai.workflow.core.workflow.registry import WorkflowRegistry

from .exceptions import WorkflowNotFoundException


class WorkflowDispatcher:
    """工作流调度器（patched：写入 im_name 供按适配器分流）"""

    def __init__(self, container: DependencyContainer):
        self.container = container
        self.logger = get_logger("WorkflowDispatcher")
        self.workflow_registry = container.resolve(WorkflowRegistry)
        self.dispatch_registry = container.resolve(DispatchRuleRegistry)

    def register_rule(self, rule: CombinedDispatchRule):
        self.dispatch_registry.register(rule)
        self.logger.info(f"Registered dispatch rule: {rule}")

    def _resolve_im_name(self, source: IMAdapter) -> str:
        name = getattr(source, "name", None) or getattr(source, "backend_name", None)
        if name:
            return str(name)
        try:
            manager = self.container.resolve(IMManager)
            for key, adapter in manager.get_adapters().items():
                if adapter is source:
                    return key
        except Exception:
            pass
        return type(source).__name__

    def _stamp_im_name(self, source: IMAdapter, message: IMMessage) -> str:
        im_name = self._resolve_im_name(source)
        try:
            if message.sender is not None:
                meta = message.sender.raw_metadata
                if meta is None:
                    message.sender.raw_metadata = {"im_name": im_name}
                else:
                    meta["im_name"] = im_name
        except Exception as exc:
            self.logger.debug(f"stamp im_name failed: {exc}")
        return im_name

    def _is_voice_bar(self, message: IMMessage) -> bool:
        try:
            from group_world_state.voice_text import is_voice_bar_event

            return bool(is_voice_bar_event(message))
        except Exception as exc:
            self.logger.debug(f"voice bar check failed: {exc}")
            return False

    async def dispatch(self, source: IMAdapter, message: IMMessage):
        im_name = self._stamp_im_name(source, message)
        if self._is_voice_bar(message):
            self.logger.debug(f"skip voice bar im={im_name} (not a message)")
            return None
        active_rules = self.dispatch_registry.get_active_rules()

        for rule in active_rules:
            if rule.match(message, self.workflow_registry):
                try:
                    self.logger.debug(
                        f"Matched rule {rule} via im={im_name}, executing workflow"
                    )
                    with self.container.scoped() as scoped_container:
                        scoped_container.register(IMAdapter, source)
                        scoped_container.register(IMMessage, message)
                        workflow = rule.get_workflow(scoped_container)
                        if workflow is None:
                            raise WorkflowNotFoundException(
                                f"Workflow for rule {rule.name} not found, please check the rule configuration"
                            )
                        scoped_container.register(Workflow, workflow)
                        executor = WorkflowExecutor(scoped_container)
                        scoped_container.register(WorkflowExecutor, executor)

                        async def _run():
                            result = await executor.run()
                            try:
                                wid = str(getattr(rule, "workflow_id", "") or "")
                                if wid.startswith("chat:"):
                                    from group_world_state.children import record as record_child
                                    record_child(str(getattr(message.sender, "user_id", "") or ""))
                            except Exception as rec_exc:
                                self.logger.debug(f"children_mode record failed: {rec_exc}")
                            return result

                        wid = str(getattr(rule, "workflow_id", "") or "")
                        # 聊天工作流按「适配器+群/私聊」串行，避免卡模型时并发串回复
                        if wid.startswith("chat:"):
                            try:
                                from group_world_state.reply_gate import begin, run_exclusive, scope_key

                                sender = message.sender
                                key = scope_key(
                                    im_name,
                                    getattr(sender, "group_id", None),
                                    getattr(sender, "user_id", None),
                                )
                                gen = await begin(key)
                                return await run_exclusive(key, gen, _run())
                            except Exception as gate_exc:
                                self.logger.warning(f"reply gate fallback: {gate_exc}")
                                return await _run()
                        return await _run()
                except Exception as e:
                    self.logger.opt(exception=e).error(
                        f"Workflow execution failed: {e}", exc_info=True
                    )
                    return None
        self.logger.debug(f"No matching rule found for message (im={im_name})")
        return None
