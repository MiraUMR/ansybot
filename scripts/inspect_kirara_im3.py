import inspect
from kirara_ai.im.manager import IMManager
print(inspect.getsource(IMManager.create_adapter))
print("--- start_adapter ---")
print(inspect.getsource(IMManager.start_adapter))

from kirara_ai.im.sender import ChatSender
print("--- ChatSender.from_c2c_chat ---")
print(inspect.getsource(ChatSender.from_c2c_chat))
print(inspect.getsource(ChatSender.from_group_chat))

from kirara_ai.im.message import TextMessage, IMMessage
print("TextMessage fields:", getattr(TextMessage, "model_fields", None) or TextMessage.__annotations__)

# send_message signature on telegram if file exists
from pathlib import Path
tg = Path("/usr/local/lib/python3.11/site-packages/im_telegram_adapter/adapter.py")
print("tg exists", tg.exists())
wecom = list(Path("/usr/local/lib/python3.11/site-packages").glob("**/im_wecom_adapter/adapter.py"))
print("wecom", wecom)
onebot = list(Path("/usr/local/lib/python3.11/site-packages").glob("**/im_onebot*/**/*.py"))
print("onebot sample", onebot[:10])
