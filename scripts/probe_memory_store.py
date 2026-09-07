import inspect
from kirara_ai.workflow.implementations.blocks.memory import chat_memory as m
print(m.__file__)
print(inspect.getsource(m.ChatMemoryStore))
