from kirara_ai.workflow.implementations.blocks.llm.chat import (
    ChatCompletion,
    _load_llm_pools,
)
import inspect

print("params", list(inspect.signature(ChatCompletion.__init__).parameters))
print("pools", _load_llm_pools())
print("ok")
