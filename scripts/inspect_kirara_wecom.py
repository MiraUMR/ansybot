from kirara_ai.im.sender import ChatType
print("ChatType", list(ChatType))

from kirara_ai.plugins.im_wecom_adapter.adapter import WecomAdapter
import inspect
print("--- WecomAdapter.start ---")
print(inspect.getsource(WecomAdapter.start)[:1500])
print("--- WecomAdapter.send_message ---")
print(inspect.getsource(WecomAdapter.send_message)[:2000])
print("--- WecomAdapter.__init__ ---")
print(inspect.getsource(WecomAdapter.__init__)[:1500])
