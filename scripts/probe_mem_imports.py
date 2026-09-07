from kirara_ai.workflow.implementations.blocks.memory import chat_memory as m
import inspect
src = inspect.getsource(m.ChatMemoryStore.execute)
print(src)
# find imports used at top of file
print('---')
print(open(m.__file__, encoding='utf-8').read().split('class ChatMemoryStore')[0])
