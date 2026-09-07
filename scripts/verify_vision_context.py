from kirara_ai.memory.composes.builtin_composes import _format_media_line
from kirara_ai.workflow.implementations.blocks.llm.chat import ChatCompletion
import inspect

print(_format_media_line("abc", "粉色头发女孩").strip())
print("persist", hasattr(ChatCompletion, "_persist_vision_context"))
src = inspect.getsource(ChatCompletion._persist_vision_context)
print("vision desc" in src or "media.description" in src)
print("ok")
